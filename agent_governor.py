#!/usr/bin/env python3
"""agent_governor.py — Executive Function & Plan Watchdog for AI Agents.

Upgraded with 6 core capabilities:
1. Intelligent diff parser & test assertion extractor (eliminates the 1000-char cutoff).
2. Repo-specific invariant discovery (.governor.json and auto-parsing CLAUDE.md).
3. "Fake Gate" command linter (flags no-op gates like 'npx tsc --noEmit').
4. "Don't Infer — List It" unprobed sequence & collision guard (PLAN-*, SPEC-*, migrations).
5. 'audit-diff' command for whole-tree git diff evaluation in ~130ms.
6. Git hook integration ('install-hook') for involuntary pre-commit enforcement.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import keyring
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

TYPESAFE_KEYRING_SERVICE = "typesafe-ai"
TYPESAFE_KEYRING_ACCOUNT = "TYPESAFE_API_KEY"

KEYRING_SERVICE = TYPESAFE_KEYRING_SERVICE
KEYRING_ACCOUNT = TYPESAFE_KEYRING_ACCOUNT

TRUSTEDROUTER_KEYRING_SERVICE = "trustedrouter"
TRUSTEDROUTER_KEYRING_ACCOUNT = "api-key"
TRUSTEDROUTER_ENV_VAR = "TRUSTEDROUTER_API_KEY"
TRUSTEDROUTER_KEY_PREFIX = "sk-tr-"
TRUSTEDROUTER_DEFAULT_BASE_URL = "https://api.trustedrouter.com/api/alpha/decide"
TRUSTEDROUTER_DEFAULT_MODEL = "typesafe-ai/jev"


class TrustedRouterClient:
    """Client for TypeSafe Jev evaluation routed through TrustedRouter."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key.strip()
        self.model = (
            model
            or os.environ.get("TRUSTEDROUTER_MODEL", "").strip()
            or TRUSTEDROUTER_DEFAULT_MODEL
        )
        self.base_url = (
            base_url
            or os.environ.get("TRUSTEDROUTER_BASE_URL", "").strip()
            or TRUSTEDROUTER_DEFAULT_BASE_URL
        )

    def system_one(
        self,
        state: Any,
        questions: Mapping[str, Any],
        *,
        model: str | None = None,
        timeout: float = 30.0,
        **_kwargs: Any,
    ) -> Any:
        norm_questions: dict[str, Any] = {}
        for name, q in questions.items():
            if isinstance(q, dict):
                norm_questions[name] = dict(q)
            else:
                qd: dict[str, Any] = {
                    "type": getattr(q, "type", "choice"),
                    "instructions": getattr(q, "instructions", ""),
                }
                criteria = getattr(q, "criteria", None)
                if criteria is not None:
                    qd["criteria"] = criteria
                norm_questions[name] = qd

        body = {
            "model": model or self.model,
            "state": state,
            "questions": norm_questions,
        }
        data_bytes = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "agent-governor/0.1.0",
            },
            data=data_bytes,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"TrustedRouter request failed (HTTP {exc.code}): {err_body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Network error contacting TrustedRouter: {exc}"
            ) from exc

        answers: dict[str, Any] = {}
        for name, ans in data.get("answers", {}).items():
            ans_type = ans.get("type")
            if ans_type == "choice":
                choice = ans.get("choice", "")
                probs = ans.get("probabilities", {})
                conf = ans.get("confidence")
                if conf is None:
                    conf = probs.get(choice, 1.0)
                answers[name] = SimpleNamespace(
                    type="choice",
                    choice=choice,
                    confidence=float(conf),
                    probabilities=probs,
                )
            elif ans_type in ("noul", "boolean"):
                noul_val = (
                    ans.get("noul")
                    if "noul" in ans
                    else ans.get("probability", 0.0)
                )
                answers[name] = SimpleNamespace(
                    type="noul",
                    noul=float(noul_val),
                )
            elif ans_type == "score":
                score_val = ans.get("score", 0.0)
                probs = ans.get("probabilities", {})
                conf = ans.get("confidence")
                if conf is None:
                    conf = max(probs.values()) if probs else 1.0
                answers[name] = SimpleNamespace(
                    type="score",
                    score=float(score_val),
                    confidence=float(conf),
                    probabilities=probs,
                )
            else:
                answers[name] = SimpleNamespace(**ans)

        return SimpleNamespace(
            model=data.get("model", self.model),
            answers=answers,
            usage=data.get("usage", {}),
            routing=data.get("trustedrouter", {}).get("routing", {}),
        )


def get_decision_client(provider: str = "auto") -> Any:
    """Create a decision client (TypeSafe or TrustedRouter) from the environment or system keyring."""
    selected_provider = provider
    if selected_provider == "auto":
        selected_provider = (
            os.environ.get("AGENT_GOVERNOR_PROVIDER", "").strip().lower()
            or os.environ.get("TYPESAFE_PROVIDER", "").strip().lower()
            or "auto"
        )

    if selected_provider not in {"auto", "typesafe", "trustedrouter"}:
        raise ValueError(
            f"Unknown provider: {selected_provider}. Choose 'auto', 'typesafe', or 'trustedrouter'."
        )

    if selected_provider == "typesafe":
        key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if not key:
            try:
                key = keyring.get_password(
                    TYPESAFE_KEYRING_SERVICE, TYPESAFE_KEYRING_ACCOUNT
                )
            except keyring.errors.KeyringError as exc:
                raise RuntimeError(
                    f"Could not read the system keyring: {exc}. "
                    "Set TYPESAFE_API_KEY in the environment instead."
                ) from exc
        if not key:
            raise RuntimeError(
                "No TypeSafe API key found. Run 'agent-governor configure --provider typesafe' or set "
                "TYPESAFE_API_KEY. Get a key at https://console.typesafe.ai/settings/keys"
            )
        return TypeSafeClient(api_key=key)

    if selected_provider == "trustedrouter":
        key = os.environ.get(TRUSTEDROUTER_ENV_VAR, "").strip()
        if not key:
            try:
                key = keyring.get_password(
                    TRUSTEDROUTER_KEYRING_SERVICE, TRUSTEDROUTER_KEYRING_ACCOUNT
                )
            except keyring.errors.KeyringError as exc:
                raise RuntimeError(
                    f"Could not read the system keyring: {exc}. "
                    f"Set {TRUSTEDROUTER_ENV_VAR} in the environment instead."
                ) from exc
        if not key:
            raise RuntimeError(
                "No TrustedRouter API key found. Run 'agent-governor configure --provider trustedrouter' or set "
                f"{TRUSTEDROUTER_ENV_VAR}. Get a key at https://trustedrouter.com/"
            )
        return TrustedRouterClient(api_key=key)

    # Auto resolution:
    typesafe_env = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if typesafe_env:
        return TypeSafeClient(api_key=typesafe_env)

    tr_env = os.environ.get(TRUSTEDROUTER_ENV_VAR, "").strip()
    if tr_env:
        return TrustedRouterClient(api_key=tr_env)

    typesafe_saved = None
    try:
        typesafe_saved = keyring.get_password(
            TYPESAFE_KEYRING_SERVICE, TYPESAFE_KEYRING_ACCOUNT
        )
    except keyring.errors.KeyringError:
        typesafe_saved = None

    if typesafe_saved:
        return TypeSafeClient(api_key=typesafe_saved)

    tr_saved = None
    try:
        tr_saved = keyring.get_password(
            TRUSTEDROUTER_KEYRING_SERVICE, TRUSTEDROUTER_KEYRING_ACCOUNT
        )
    except keyring.errors.KeyringError:
        tr_saved = None

    if tr_saved:
        return TrustedRouterClient(api_key=tr_saved)

    raise RuntimeError(
        "No Jev credentials found. Run 'agent-governor configure' or set "
        "TYPESAFE_API_KEY or TRUSTEDROUTER_API_KEY in the environment."
    )


def get_typesafe_client(provider: str = "auto") -> Any:
    """Create a Jev decision client from the environment or system keyring."""
    return get_decision_client(provider=provider)


def configure_key(provider: str = "auto") -> str:
    """Store a TypeSafe or TrustedRouter key in the system keyring."""
    if provider == "trustedrouter":
        prompt = "TrustedRouter API key: "
    elif provider == "typesafe":
        prompt = "TypeSafe API key: "
    else:
        prompt = "API key (TypeSafe or TrustedRouter): "

    key = getpass.getpass(prompt).strip()
    if not key:
        raise RuntimeError("No API key entered.")

    target_provider = provider
    if target_provider == "auto":
        target_provider = (
            "trustedrouter"
            if key.startswith(TRUSTEDROUTER_KEY_PREFIX)
            else "typesafe"
        )

    if target_provider == "trustedrouter":
        service = TRUSTEDROUTER_KEYRING_SERVICE
        account = TRUSTEDROUTER_KEYRING_ACCOUNT
        label = "TrustedRouter"
        env_var = TRUSTEDROUTER_ENV_VAR
    else:
        service = TYPESAFE_KEYRING_SERVICE
        account = TYPESAFE_KEYRING_ACCOUNT
        label = "TypeSafe"
        env_var = "TYPESAFE_API_KEY"

    try:
        keyring.set_password(service, account, key)
    except keyring.errors.KeyringError as exc:
        raise RuntimeError(
            f"Could not save to the system keyring: {exc}. "
            f"Set {env_var} in the environment instead."
        ) from exc
    return label


def install_agent_skill(scope: str, base_dir: Path, force: bool = False) -> list[Path]:
    """Install the bundled skill where supported coding agents discover it."""
    if scope == "user":
        parents = (
            ".agents/skills", ".claude/skills",
            ".gemini/config/skills", ".gemini/antigravity-cli/skills",
        )
    elif scope == "project":
        parents = (".agents/skills", ".claude/skills", ".grok/skills")
    else:
        raise ValueError(f"Unknown skill scope: {scope}")

    content = files("agent_governor_skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    destinations = [base_dir / parent / "agent-governor" / "SKILL.md" for parent in parents]
    conflicts = [path for path in destinations if path.exists() and path.read_text(encoding="utf-8") != content]
    if conflicts and not force:
        raise RuntimeError(
            "Existing agent-governor skill differs at " + ", ".join(str(path) for path in conflicts)
            + ". Re-run with --force to replace it."
        )
    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return destinations

LEDGER_FILE = Path.home() / ".agent_governor" / "ledger.jsonl"

ASSERTION_KEYWORD_REGEX = re.compile(
    r"\b(expect\b|assert\b|toBe\b|toEqual\b|toStrictEqual\b|toMatch\b|toContain\b|"
    r"should\b|assertTrue\b|assertFalse\b|assertEqual\b|assertNotEqual\b|"
    r"assert_called\b|assert_true\b|assert_false\b|toBeGreaterThan\b|toBeLessThan\b|"
    r"\.skip\b|\bxit\(|\bxtest\(|"
    r"assertIs\b|assertIsNot\b|assertIn\b|assertNotIn\b|assertRaises\b|"
    r"assertRaisesRegex\b|assertAlmostEqual\b|assertGreater\b|assertLess\b|"
    r"assertCountEqual\b|assertListEqual\b|assertDictEqual\b|assertIn\b|"
    r"self\.assert|unittest\.assert|pytest\.raises|pytest\.fail|pytest\.skip|"
    r"expected\s*=|self\.fail\(|raise\s+self\.failureException)"
)

PYTEST_CONFIG_FILES = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "conftest.py")

NUMBERED_ARTIFACT_REGEX = re.compile(
    r"(?:future-work/|docs/|supabase/migrations/)?(PLAN-(\d+)|SPEC-(\d+)|(\d{4})_[a-z0-9_]+\.sql)"
)

DEFAULT_FAKE_GATES = {
    "npx tsc --noEmit": {
        "replacement": "npm run typecheck (tsc -b --noEmit)",
        "rationale": "Root tsconfig.json has 'files: []'. Running 'npx tsc --noEmit' checks NOTHING and exits 0 silently."
    },
    "tsc --noEmit": {
        "replacement": "npm run typecheck (tsc -b --noEmit)",
        "rationale": "Root tsconfig.json is a project reference shell. Must use 'npm run typecheck'."
    },
    "eslint .": {
        "replacement": "npx eslint src",
        "rationale": "'eslint .' walks into .claude/worktrees/ or node_modules and double-counts or errors on non-source."
    },
    "npx eslint .": {
        "replacement": "npx eslint src",
        "rationale": "'eslint .' walks into .claude/worktrees/ or node_modules. Target 'src' specifically."
    }
}


# ==============================================================================
# 1. UI & Formatting
# ==============================================================================

def print_banner(status: str, goal: str, action: str, target_file: str, rationale: str, metrics: dict):
    """Emits prominent visible notification box to stderr."""
    border = "─" * 72
    icon = "🛡️" if status == "ALLOW" else "🛑"
    color = "\033[92m" if status == "ALLOW" else "\033[91m"
    reset = "\033[0m"

    sys.stderr.write(f"\n{color}╭{border}╮{reset}\n")
    sys.stderr.write(f"{color}│ {icon} AGENT GOVERNOR INTERVENTION: {status:<41} │{reset}\n")
    sys.stderr.write(f"{color}├{border}┤{reset}\n")
    sys.stderr.write(f"│ Goal:      {goal[:59]:<59} │\n")
    if target_file:
        sys.stderr.write(f"│ File:      {target_file[:59]:<59} │\n")
    sys.stderr.write(f"│ Action:    {action[:59]:<59} │\n")
    risk_str = f"Risk Score: {metrics.get('risk_score', 0):.2f}" if "risk_score" in metrics else "Pre-Flight Guard"
    sys.stderr.write(f"│ Verdict:   {status:<25} ({risk_str:<23}) │\n")
    sys.stderr.write(f"│ Rationale: {rationale[:59]:<59} │\n")
    sys.stderr.write(f"{color}╰{border}╯{reset}\n\n")
    sys.stderr.flush()


# ==============================================================================
# 2. Intelligent Diff Parser & Test Assertion Extractor
# ==============================================================================

def parse_diff_summary(diff_text: str) -> dict:
    """Parses git diff into a structured summary without blind truncation."""
    current_file = None
    files_modified = []
    file_statuses = {}
    assertion_changes = []
    tamper_suspect = False
    migration_violations = []
    sensitive_files = []
    diff_lines_compact = []

    lines = diff_text.splitlines()
    for line in lines:
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                b_path = parts[3].replace("b/", "", 1)
                current_file = b_path
                if current_file not in files_modified:
                    files_modified.append(current_file)
                file_statuses[current_file] = "M"
        elif line.startswith("new file mode"):
            if current_file:
                file_statuses[current_file] = "A"
        elif line.startswith("deleted file mode"):
            if current_file:
                file_statuses[current_file] = "D"
        elif line.startswith("+++ b/"):
            current_file = line[6:].strip()
            if current_file not in files_modified:
                files_modified.append(current_file)
        elif line.startswith(("---", "+++", "index ", "@@")):
            continue
        elif current_file:
            # Check for existing migration modifications
            if "supabase/migrations/" in current_file:
                status = file_statuses.get(current_file, "M")
                if status == "M" and current_file not in migration_violations:
                    migration_violations.append(current_file)

            # Check for sensitive environment reference files
            if any(current_file.endswith(s) for s in [".prod-ref", ".staging-ref", ".env.local"]):
                if current_file not in sensitive_files:
                    sensitive_files.append(current_file)

            # Check for test assertion modifications
            is_test_file = any(t in current_file.lower() for t in ["test.", "spec.", "tests/", "__tests__/"])
            if is_test_file and line.startswith(("-", "+")):
                if ASSERTION_KEYWORD_REGEX.search(line):
                    assertion_changes.append({"file": current_file, "line": line})
                    # Heuristic for test tampering: weakening or skipping
                    if line.startswith("+") and any(w in line for w in [".skip", "xit(", "xtest(", "toBeGreaterThan", "toBeDefined", "toBeTruthy"]):
                        tamper_suspect = True
                    if line.startswith("-") and any(w in line for w in ["toBe(", "toEqual(", "assert "]):
                        tamper_suspect = True

            # Keep a sampled compact diff
            if len(diff_lines_compact) < 150:
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                    diff_lines_compact.append(f"{current_file}: {line[:120]}")

    return {
        "files_modified": files_modified,
        "file_statuses": file_statuses,
        "assertion_changes": assertion_changes[:20],
        "tamper_suspect": tamper_suspect,
        "migration_violations": migration_violations,
        "sensitive_files": sensitive_files,
        "compact_diff": "\n".join(diff_lines_compact[:100])
    }


# ==============================================================================
# 3. Repository Invariants Discovery
# ==============================================================================

def find_repo_root(start_dir: Path | None = None) -> Path:
    """Finds repository root by walking up looking for .git or CLAUDE.md."""
    curr = (start_dir or Path.cwd()).resolve()
    for p in [curr, *curr.parents]:
        if (p / ".git").exists() or (p / "CLAUDE.md").exists():
            return p
    return curr


def get_repo_invariants(target_dir: Path | None = None) -> dict:
    """Loads repository invariants from .governor.json or parses CLAUDE.md."""
    repo_root = find_repo_root(target_dir)
    invariants = [
        "Ensure all test assertions remain strict and test real logic.",
        "Never delete or bypass tests to force a green build.",
        "Keep changes tightly scoped to the explicit task."
    ]
    fake_gates = dict(DEFAULT_FAKE_GATES)
    protected_patterns = [r"\.prod-ref$", r"\.staging-ref$", r"supabase/migrations/.*"]

    # 1. Check for explicit .governor.json
    gov_file = repo_root / ".governor.json"
    if gov_file.exists():
        try:
            with open(gov_file) as f:
                data = json.load(f)
                invariants.extend(data.get("invariants", []))
                fake_gates.update(data.get("fake_gates", {}))
                protected_patterns.extend(data.get("protected_patterns", []))
            return {
                "invariants": list(dict.fromkeys(invariants)),
                "fake_gates": fake_gates,
                "protected_patterns": protected_patterns,
                "repo_root": str(repo_root)
            }
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to parse {gov_file}: {e}\n")

    # 2. Auto-parse CLAUDE.md if present
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        try:
            text = claude_md.read_text(errors="ignore")
            # Extract bullet points under key sections
            section_matches = re.findall(
                r"##\s+(?:Structural invariants|Database and migrations|Environments|Gates|Don't infer the state of the world|Design tokens)[^\n]*\n(.*?)(?=\n##|\Z)",
                text,
                re.DOTALL | re.IGNORECASE
            )
            for sec in section_matches:
                bullets = re.findall(r"^[*-]\s+(.+)$", sec, re.MULTILINE)
                for b in bullets[:4]:
                    cleaned = re.sub(r"\[.*?\]|\(.*?\)|[*_`]", "", b).strip()
                    if len(cleaned) > 20:
                        invariants.append(cleaned[:160])
        except Exception:
            pass

    return {
        "invariants": list(dict.fromkeys(invariants))[:8],
        "fake_gates": fake_gates,
        "protected_patterns": protected_patterns,
        "repo_root": str(repo_root)
    }


# ==============================================================================
# 4. Fake Gate / Command Linter
# ==============================================================================

def lint_command(command_str: str, repo_dir: Path | None = None) -> dict:
    """Checks if a command is a known fake gate that exits 0 without verifying."""
    invariants_cfg = get_repo_invariants(repo_dir)
    fake_gates = invariants_cfg.get("fake_gates", {})

    cmd_stripped = command_str.strip()

    # Check for failure masking: operators that force success regardless of result
    masking_match = re.search(r"(\|\|\s*true\b|\|\|\s*echo\b|;\s*exit\s+0\b|&&\s*exit\s+0\b|2>\s*/dev/null\b|>\s*/dev/null\s+2>&1\b)", cmd_stripped)
    if masking_match:
        return {
            "status": "FAIL",
            "command": cmd_stripped,
            "fake_gate": masking_match.group(1).strip(),
            "replacement": cmd_stripped.replace(masking_match.group(1).strip(), "").strip().rstrip(";&| ") or cmd_stripped,
            "rationale": f"Failure-masking operator '{masking_match.group(1).strip()}' forces exit 0 / hides errors, so the command cannot fail a gate even when verification fails."
        }

    # Check for pure no-op commands
    if re.fullmatch(r"(sudo\s+)?(true|:)(\s+#.*)?", cmd_stripped):
        return {
            "status": "FAIL",
            "command": cmd_stripped,
            "fake_gate": cmd_stripped,
            "replacement": "Run the real verification command (tests, lint, typecheck).",
            "rationale": "Command is a shell no-op ('true'/':') that exits 0 without verifying anything."
        }

    # Check for empty test discovery: unittest that matches nothing (static check, no execution)
    if re.search(r"\bunittest\b", cmd_stripped) and re.search(r"-p\s+[\"']?([*.\w]+)[\"']?", cmd_stripped):
        pattern_match = re.search(r"-p\s+[\"']?([*.\w]+)[\"']?", cmd_stripped)
        pattern = pattern_match.group(1)
        if not re.search(r"test", pattern, re.IGNORECASE):
            return {
                "status": "FAIL",
                "command": cmd_stripped,
                "fake_gate": f"-p {pattern}",
                "replacement": "Use a pattern that matches test files, e.g. -p 'test_*.py'.",
                "rationale": f"Discovery pattern '{pattern}' matches no test files, so 'unittest discover' reports 'Ran 0 tests ... OK' — a silent no-op gate."
            }

    # Direct match or substring match
    for fake, details in fake_gates.items():
        if fake in cmd_stripped:
            return {
                "status": "FAIL",
                "command": cmd_stripped,
                "fake_gate": fake,
                "replacement": details["replacement"],
                "rationale": details["rationale"]
            }

    # Check for bare vitest when running DB tests
    if "vitest" in cmd_stripped and "test:db" not in cmd_stripped and "run" not in cmd_stripped:
        return {
            "status": "WARN",
            "command": cmd_stripped,
            "fake_gate": "bare vitest",
            "replacement": "npm run test:db",
            "rationale": "Bare vitest inherits a dirty database. In this repo, DB tests require 'npm run test:db' (which runs db reset first)."
        }

    # Check for concurrent vitest process collision if running DB test
    if "test:db" in cmd_stripped or "vitest" in cmd_stripped:
        try:
            ps_out = subprocess.run(["pgrep", "-f", "vitest"], capture_output=True, text=True).stdout.strip()
            pids = ps_out.splitlines()
            if len(pids) > 1:
                return {
                    "status": "WARN",
                    "command": cmd_stripped,
                    "fake_gate": "concurrent vitest",
                    "replacement": "Wait for active vitest run to complete",
                    "rationale": f"Detected {len(pids)} active vitest processes. Concurrent runs reset the DB and destroy each other's state."
                }
        except Exception:
            pass

    return {"status": "PASS", "command": cmd_stripped}


# ==============================================================================
# 5. "Don't Infer — List It" Unprobed Precondition Guard
# ==============================================================================

def check_unprobed_state(action: str, target_file: str, repo_dir: Path | None = None) -> dict:
    """Detects sequence number guessing or creating colliding numbered artifacts."""
    repo_root = find_repo_root(repo_dir)

    target_path = Path(target_file) if target_file else None
    if not target_path and action:
        match = re.search(r"(\S+\.(?:md|sql|ts|js))\b", action)
        if match:
            target_path = Path(match.group(1))

    if not target_path:
        return {"status": "ALLOW"}

    # Resolve relative to repo root if needed
    if not target_path.is_absolute():
        full_path = repo_root / target_path
    else:
        full_path = target_path

    # 1. Collision check: only for sequence-sensitive numbered artifacts
    #    (plans, specs, migrations). Ordinary source files are legitimately
    #    overwritten/rewritten during normal editing workflows.
    is_numbered_artifact = bool(
        re.search(r"PLAN-(\d+)|SPEC-(\d+)|^(\d{4})_", target_path.name)
    ) or "supabase/migrations/" in str(target_path)
    is_create_action = any(w in action.lower() for w in ["create", "new file", "touch"])
    if is_numbered_artifact and is_create_action and full_path.exists():
        return {
            "status": "BLOCK_COLLISION",
            "rationale": f"Numbered artifact '{target_path}' already exists on disk. Do not overwrite existing plans, specs, or migrations without explicit listing."
        }

    # 2. Numbered sequence check for plans / migrations
    parent_dir = full_path.parent
    if parent_dir.exists():
        # Check PLAN-XX
        plan_match = re.search(r"PLAN-(\d+)", target_path.name)
        if plan_match:
            proposed_num = int(plan_match.group(1))
            existing_plans = [
                int(m.group(1))
                for f in parent_dir.iterdir()
                if (m := re.search(r"PLAN-(\d+)", f.name))
            ]
            if existing_plans:
                highest = max(existing_plans)
                if proposed_num <= highest:
                    return {
                        "status": "BLOCK_NUMBER_COLLISION",
                        "rationale": f"Proposed PLAN-{proposed_num} already exists or is taken. Highest existing plan in {parent_dir.name} is PLAN-{highest}."
                    }
                elif proposed_num > highest + 1:
                    return {
                        "status": "WARN_SEQUENCE_GAP",
                        "rationale": f"Proposed PLAN-{proposed_num} skips sequence. Highest existing is PLAN-{highest}. Verify with 'ls {parent_dir.name}/'."
                    }

        # Check migration numbers (e.g. 0338_...)
        mig_match = re.search(r"^(\d{4})_", target_path.name)
        if mig_match:
            proposed_mig = int(mig_match.group(1))
            existing_migs = [
                int(m.group(1))
                for f in parent_dir.iterdir()
                if (m := re.search(r"^(\d{4})_", f.name))
            ]
            if existing_migs:
                highest_mig = max(existing_migs)
                if proposed_mig <= highest_mig:
                    return {
                        "status": "BLOCK_MIGRATION_COLLISION",
                        "rationale": f"Migration {proposed_mig:04d} already exists. Highest existing is {highest_mig:04d}. Migrations must be strictly append-only."
                    }

    return {"status": "ALLOW"}


# ==============================================================================
# 6. Runtime Action & Tool Call Verification (check)
# ==============================================================================

def check_action(client, goal: str, plan: str, action: str, target_file: str, diff_snippet: str = "") -> dict:
    """Evaluates agent tool call against goal, plan, and repo invariants."""
    repo_cfg = get_repo_invariants()
    invariants = repo_cfg["invariants"]

    # 1. Gate Linter Check (trigger on known runners OR any shell-chained command)
    _lint_triggers = ("npx ", "npm ", "tsc", "eslint", "vitest", "pytest", "cargo ",
                      "python", "unittest", "make ", "go test", "rake", "gradle",
                      "mvn ", "2>", "/dev/null")
    if action.startswith(_lint_triggers) or re.search(r"\|\||&&|;\s*exit|\| true|2>\s*/dev/null", action):
        lint_res = lint_command(action)
        if lint_res["status"] == "FAIL":
            return {
                "status": "BLOCK_FAKE_GATE",
                "rationale": f"{lint_res['rationale']} Replace with: {lint_res['replacement']}",
                "metrics": {"risk_score": 2.0}
            }

    # 2. Unprobed State Check
    unprobed_res = check_unprobed_state(action, target_file)
    if unprobed_res["status"].startswith("BLOCK"):
        return {
            "status": unprobed_res["status"],
            "rationale": unprobed_res["rationale"],
            "metrics": {"risk_score": 1.8}
        }

    # 3. Direct Invariant Checks on Target File
    if target_file:
        if "supabase/migrations/" in target_file and any(w in action.lower() for w in ["edit", "modify", "update", "replace", "fix"]):
            # Check if file exists in git
            repo_root = Path(repo_cfg["repo_root"])
            mig_path = repo_root / target_file
            if mig_path.exists():
                return {
                    "status": "BLOCK_REPO_INVARIANT_VIOLATION",
                    "rationale": f"Existing migration '{target_file}' cannot be modified. Migrations are strictly append-only. Create a new migration file.",
                    "metrics": {"risk_score": 2.0}
                }
        if any(target_file.endswith(s) for s in [".prod-ref", ".staging-ref"]):
            return {
                "status": "BLOCK_REPO_INVARIANT_VIOLATION",
                "rationale": f"Direct modification of environment ref '{target_file}' is forbidden. Project refs must not be altered.",
                "metrics": {"risk_score": 2.0}
            }

    # 4. Structured Diff Parsing
    diff_summary = parse_diff_summary(diff_snippet) if diff_snippet else {}

    state = {
        "original_goal": goal,
        "approved_plan": plan or "Follow minimal direct steps to achieve goal",
        "agent_proposed_action": action,
        "target_file": target_file,
        "repo_invariants": invariants,
        "assertion_changes": diff_summary.get("assertion_changes", []),
        "tamper_suspect": diff_summary.get("tamper_suspect", False),
        "diff_compact": diff_summary.get("compact_diff", "")
    }

    resp = client.system_one(
        state=state,
        questions={
            "alignment": Choice(
                instructions="Evaluate how the agent's action relates to the approved plan and goal.",
                criteria={
                    "on_track": "Direct execution of a plan step or normal immediate verification.",
                    "reasonable_prereq": "Valid prerequisite or debugging directly caused by the plan step.",
                    "drift_rabbit_hole": "Unrelated detour, premature optimization, or scope creep away from the goal."
                }
            ),
            "is_scope_creep": Noul(
                instructions="Is this action scope creep or an unapproved tangent away from the original goal?"
            ),
            "is_test_tampering": Noul(
                instructions="Is the agent weakening, bypassing, commenting out, or cheating test assertions rather than fixing actual source code?",
                criteria={
                    "true": "Weakening assertions, commenting out tests, mocking away the real logic to fake a pass",
                    "false": "Legitimate code fix or adding a new valid test case"
                }
            ),
            "violates_invariants": Noul(
                instructions="Does this proposed action violate any of the specified repository invariants?"
            ),
            "risk_severity": Score(
                instructions="Rate the integrity risk of this action to the codebase.",
                criteria=["Safe / on plan", "Questionable detour", "Severe breach of integrity, cheat, or destructive rabbit hole"]
            )
        }
    )

    ans = resp.answers
    align = ans["alignment"]
    creep = ans["is_scope_creep"]
    tamper = ans["is_test_tampering"]
    invar = ans["violates_invariants"]
    risk = ans["risk_severity"]

    # Decision policy
    if invar.noul >= 0.70:
        status = "BLOCK_REPO_INVARIANT_VIOLATION"
        rationale = f"Action violates repository structural invariants (prob: {invar.noul:.2f})"
    elif tamper.noul >= 0.70 or (diff_summary.get("tamper_suspect") and tamper.noul >= 0.50):
        status = "BLOCK_TEST_TAMPERING"
        rationale = f"Detected attempt to weaken or fake test assertion (tamper prob: {tamper.noul:.2f})"
    elif creep.noul >= 0.75 or (align.choice == "drift_rabbit_hole" and align.confidence >= 0.70):
        status = "BLOCK_SCOPE_CREEP"
        rationale = f"Action diverges from plan into unrelated rabbit hole (creep prob: {creep.noul:.2f})"
    elif risk.score >= 1.50 and risk.confidence >= 0.70:
        status = "BLOCK_HIGH_RISK"
        rationale = f"Action carries dangerous blast radius (risk score: {risk.score:.2f})"
    elif creep.noul >= 0.50:
        status = "WARN_DRIFT"
        rationale = "Action is borderline detour; verify alignment before proceeding."
    else:
        status = "ALLOW"
        rationale = "Action is aligned with approved plan."

    metrics = {
        "alignment_choice": align.choice,
        "alignment_confidence": round(align.confidence, 2),
        "scope_creep_noul": round(creep.noul, 2),
        "test_tampering_noul": round(tamper.noul, 2),
        "violates_invariants_noul": round(invar.noul, 2),
        "risk_score": round(risk.score, 2),
    }

    return {
        "status": status,
        "rationale": rationale,
        "metrics": metrics
    }


# ==============================================================================
# 7. Git Working Tree & Pre-Commit Evaluation (audit-diff)
# ==============================================================================

def audit_diff(client, goal: str, target_dir: Path | None = None, staged_only: bool = False) -> dict:
    """Evaluates entire git diff (staged or working tree) before commit or push."""
    repo_probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=target_dir or Path.cwd(), capture_output=True, text=True
    )
    if repo_probe.returncode != 0:
        raise RuntimeError("audit-diff requires a Git repository; run it there or pass --dir")
    repo_root = Path(repo_probe.stdout.strip())

    has_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root, capture_output=True, text=True
    ).returncode == 0
    if staged_only:
        diff_cmd = ["git", "diff", "--staged"]
    else:
        diff_cmd = ["git", "diff", "HEAD"] if has_head else ["git", "diff"]
    diff_proc = subprocess.run(diff_cmd, cwd=repo_root, capture_output=True, text=True)
    if diff_proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {diff_proc.stderr.strip()}")
    diff_text = diff_proc.stdout.strip()

    # If HEAD diff is empty and not staged, check plain working tree diff
    if not diff_text and not staged_only:
        diff_proc2 = subprocess.run(["git", "diff"], cwd=repo_root, capture_output=True, text=True)
        if diff_proc2.returncode != 0:
            raise RuntimeError(f"git diff failed: {diff_proc2.stderr.strip()}")
        diff_text = diff_proc2.stdout.strip()

    # Parse diff
    summary = parse_diff_summary(diff_text)
    repo_cfg = get_repo_invariants(repo_root)

    # Capture untracked files (invisible to 'git diff' but part of the change set)
    untracked_out = ""
    if not staged_only:
        untracked_proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=repo_root, capture_output=True, text=True
        )
        if untracked_proc.returncode != 0:
            raise RuntimeError(f"git ls-files failed: {untracked_proc.stderr.strip()}")
        untracked_out = untracked_proc.stdout.strip()
    untracked_files = [u for u in untracked_out.splitlines() if u] if untracked_out else []
    if not diff_text and not untracked_files:
        return {
            "status": "ALLOW",
            "rationale": "Git working tree is clean. No diff to audit.",
            "metrics": {"risk_score": 0.0}
        }
    if untracked_files:
        sampled_lines = summary["compact_diff"].splitlines()
        for u in untracked_files:
            if u not in summary["files_modified"]:
                summary["files_modified"].append(u)
                summary["file_statuses"][u] = "A"
                try:
                    content = (repo_root / u).read_text(errors="ignore")
                except OSError:
                    continue
                if any(t in u.lower() for t in ["test.", "spec.", "tests/", "__tests__/"]):
                    if ASSERTION_KEYWORD_REGEX.search(content):
                        summary["assertion_changes"].append({"file": u, "line": "(untracked new test file)"})
                for line in content.splitlines()[:20]:
                    if len(sampled_lines) >= 100:
                        break
                    sampled_lines.append(f"{u}: +{line[:120]}")
        summary["compact_diff"] = "\n".join(sampled_lines)

    # 1. Deterministic Invariant Violations
    if summary["migration_violations"]:
        violating = summary["migration_violations"][0]
        return {
            "status": "BLOCK_REPO_INVARIANT_VIOLATION",
            "rationale": f"Modified existing migration '{violating}'. Migrations are strictly append-only. Add the next numbered migration instead.",
            "metrics": {"risk_score": 2.0}
        }

    if summary["sensitive_files"]:
        violating = summary["sensitive_files"][0]
        return {
            "status": "BLOCK_REPO_INVARIANT_VIOLATION",
            "rationale": f"Direct modification of environment reference file '{violating}' is blocked.",
            "metrics": {"risk_score": 2.0}
        }

    # 2. Jev System One Evaluation of Net Diff
    state = {
        "stated_goal": goal or "General codebase modification",
        "files_modified": summary["files_modified"],
        "file_count": len(summary["files_modified"]),
        "file_statuses": summary["file_statuses"],
        "untracked_files": untracked_files,
        "assertion_changes": summary["assertion_changes"],
        "tamper_suspect": summary["tamper_suspect"],
        "repo_invariants": repo_cfg["invariants"],
        "compact_diff": summary["compact_diff"]
    }

    resp = client.system_one(
        state=state,
        questions={
            "alignment": Choice(
                instructions="Does this net git diff correspond directly to the stated goal?",
                criteria={
                    "on_track": "Changes directly solve the goal with minimal churn.",
                    "reasonable_prereq": "Contains reasonable supporting fixes or tests.",
                    "drift_rabbit_hole": "Contains substantial unrelated edits, opportunistic refactors, or scope creep."
                }
            ),
            "is_test_tampering": Noul(
                instructions="Do any of the test file modifications weaken, fake, or disable test assertions rather than maintaining rigorous verification?"
            ),
            "violates_invariants": Noul(
                instructions="Do the changes in this git diff violate any of the specified repository invariants?"
            ),
            "blast_radius": Score(
                instructions="Rate the blast radius of this diff.",
                criteria=["Low: tightly scoped", "Medium: touches multiple modules", "High: widespread architectural churn"]
            )
        }
    )

    ans = resp.answers
    align = ans["alignment"]
    tamper = ans["is_test_tampering"]
    invar = ans["violates_invariants"]
    blast = ans["blast_radius"]

    if invar.noul >= 0.70:
        status = "BLOCK_REPO_INVARIANT_VIOLATION"
        rationale = f"Git diff violates repository structural invariants (prob: {invar.noul:.2f})"
    elif tamper.noul >= 0.70 or (summary["tamper_suspect"] and tamper.noul >= 0.50):
        status = "BLOCK_TEST_TAMPERING"
        rationale = f"Git diff modifies or weakens test assertions (tamper prob: {tamper.noul:.2f})"
    elif align.choice == "drift_rabbit_hole" and align.confidence >= 0.70:
        status = "BLOCK_SCOPE_CREEP"
        rationale = f"Git diff wanders into unrelated files beyond the stated goal ({len(summary['files_modified'])} files touched)"
    elif blast.score >= 1.70 and blast.confidence >= 0.70:
        status = "BLOCK_HIGH_RISK"
        rationale = f"Blast radius is dangerously broad ({len(summary['files_modified'])} files, score {blast.score:.2f})"
    else:
        status = "ALLOW"
        rationale = f"Diff verified clean ({len(summary['files_modified'])} files modified, blast radius: {blast.score:.2f})"

    metrics = {
        "alignment": align.choice,
        "tamper_noul": round(tamper.noul, 2),
        "invariants_noul": round(invar.noul, 2),
        "risk_score": round(blast.score, 2),
        "files_modified_count": len(summary["files_modified"]),
        "untracked_files_count": len(untracked_files)
    }

    return {
        "status": status,
        "rationale": rationale,
        "metrics": metrics
    }


# ==============================================================================
# 8. Plan Auditing (audit-plan)
# ==============================================================================

def audit_plan(client, goal: str, plan_text: str) -> dict:
    """Evaluates a multi-step plan before execution starts."""
    state = {
        "goal": goal,
        "proposed_plan": plan_text
    }

    resp = client.system_one(
        state=state,
        questions={
            "feasibility": Choice(
                instructions="Assess overall plan viability.",
                criteria={
                    "sound": "Direct, minimal, well-sequenced steps achieving the exact goal",
                    "over_engineered": "Overly complicated, unnecessary rewrites or abstractions",
                    "incomplete": "Missing crucial verification, error handling, or rollback steps"
                }
            ),
            "is_over_engineered": Noul(
                instructions="Does this plan attempt an unnecessary refactor or over-complicated design?"
            ),
            "blast_radius": Score(
                instructions="Rate the architectural blast radius of this plan.",
                criteria=["Low: isolated change", "Medium: multi-file/component", "High: systemic migration or broad API break"]
            )
        }
    )

    ans = resp.answers
    feas = ans["feasibility"]
    over = ans["is_over_engineered"]
    blast = ans["blast_radius"]

    return {
        "feasibility": feas.choice,
        "feasibility_confidence": round(feas.confidence, 2),
        "is_over_engineered": round(over.noul, 2),
        "blast_radius_score": round(blast.score, 2)
    }


# ==============================================================================
# 9. Git Hook Installer (install-hook)
# ==============================================================================

def install_hook(repo_path: Path | None = None, hook_type: str = "pre-commit") -> str:
    """Installs involuntary git hook to run audit-diff before commit."""
    repo_root = find_repo_root(repo_path)
    hooks_dir = repo_root / ".git" / "hooks"

    if not hooks_dir.exists():
        raise RuntimeError(f"No .git/hooks directory found at {hooks_dir}. Is this a git repository?")

    hook_file = hooks_dir / hook_type

    script_content = f"""#!/bin/sh
# Agent Governor Involuntary Safety Hook ({hook_type})
# Automatically verifies staged changes for test-tampering, migration violations, and scope creep.

if ! command -v agent-governor >/dev/null 2>&1; then
    echo "Agent Governor is not on PATH. Activate its Python environment or reinstall it." >&2
    exit 1
fi
agent-governor audit-diff --staged --quiet-allow || {{
    echo ""
    echo "🛑 Commit rejected by Agent Governor. Resolve the violation before committing."
    exit 1
}}
exit 0
"""

    hook_file.write_text(script_content)
    hook_file.chmod(0o755)
    return str(hook_file)


# ==============================================================================
# 10. Telemetry & Main CLI Entrypoint
# ==============================================================================

def log_telemetry(entry: dict):
    """Logs governor action to ~/.agent_governor/ledger.jsonl."""
    try:
        LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        sys.stderr.write(f"Failed to log governor telemetry: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="AgentGovernor: Executive watchdog & anti-drift supervisor.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: check
    check_p = subparsers.add_parser("check", help="Check proposed tool call / action for plan drift or tampering")
    check_p.add_argument("--goal", "-g", required=True, help="Original user task / goal")
    check_p.add_argument("--plan", "-p", default="", help="Approved plan steps")
    check_p.add_argument("--action", "-a", required=True, help="Proposed action / tool invocation")
    check_p.add_argument("--file", "-f", default="", help="Target file path")
    check_p.add_argument("--diff", "-d", default="", help="Optional diff snippet")
    check_p.add_argument("--provider", choices=["auto", "typesafe", "trustedrouter"], default="auto", help="Decision model provider (default: auto)")
    check_p.add_argument("--json", action="store_true", help="Output JSON on stdout")
    check_p.add_argument("--quiet", action="store_true", help="Suppress stderr banner")
    check_p.add_argument("--no-exit-code", action="store_true", help="Always exit 0 even if blocked")

    # Subcommand: audit-diff
    diff_p = subparsers.add_parser("audit-diff", help="Audit git working tree or staged diff")
    diff_p.add_argument("--goal", "-g", default="Maintain clean code and intended functionality", help="Target goal")
    diff_p.add_argument("--staged", action="store_true", help="Only audit staged changes")
    diff_p.add_argument("--dir", "-C", default="", help="Repository directory (defaults to cwd)")
    diff_p.add_argument("--provider", choices=["auto", "typesafe", "trustedrouter"], default="auto", help="Decision model provider (default: auto)")
    diff_p.add_argument("--quiet-allow", action="store_true", help="Suppress output on ALLOW (clean for git hooks)")
    diff_p.add_argument("--json", action="store_true", help="Output JSON")
    diff_p.add_argument("--no-exit-code", action="store_true", help="Always exit 0 even if blocked")

    # Subcommand: lint-command
    lint_p = subparsers.add_parser("lint-command", help="Check verification commands for known fake gates")
    lint_p.add_argument("command", help="Command string to lint")
    lint_p.add_argument("--json", action="store_true", help="Output JSON")

    # Subcommand: audit-plan
    audit_p = subparsers.add_parser("audit-plan", help="Audit a proposed plan before execution")
    audit_p.add_argument("--goal", "-g", required=True, help="Target goal")
    audit_p.add_argument("--plan", "-p", required=True, help="Proposed plan text")
    audit_p.add_argument("--provider", choices=["auto", "typesafe", "trustedrouter"], default="auto", help="Decision model provider (default: auto)")
    audit_p.add_argument("--json", action="store_true", help="Output JSON")

    # Subcommand: install-hook
    hook_p = subparsers.add_parser("install-hook", help="Install git pre-commit safety hook")
    hook_p.add_argument("--repo-path", "-r", default="", help="Path to repository")
    hook_p.add_argument("--type", default="pre-commit", choices=["pre-commit", "pre-push"], help="Hook type")

    # Subcommand: report
    subparsers.add_parser("report", help="Analyze recent interventions and drift events")

    # Subcommand: configure
    config_p = subparsers.add_parser("configure", help="Save a TypeSafe or TrustedRouter API key in the system keyring")
    config_p.add_argument("--provider", choices=["auto", "typesafe", "trustedrouter"], default="auto", help="Provider to configure (default: auto detect)")

    # Subcommand: install-skill
    skill_p = subparsers.add_parser("install-skill", help="Install the agent skill for supported coding agents")
    skill_p.add_argument("--scope", choices=["user", "project"], default="user", help="Install for this user or one project")
    skill_p.add_argument("--dir", default="", help="Target project directory (with --scope project)")
    skill_p.add_argument("--force", action="store_true", help="Replace existing copies of the skill")

    args = parser.parse_args()

    # Commands not needing Jev client
    if args.subcommand == "lint-command":
        res = lint_command(args.command)
        if args.json:
            print(json.dumps(res, indent=2))
            sys.exit(1 if res["status"] == "FAIL" else 0)
        else:
            if res["status"] == "FAIL":
                print(f"🛑 FAKE GATE DETECTED: {res['rationale']}")
                print(f"👉 Recommended replacement: {res['replacement']}")
                sys.exit(1)
            elif res["status"] == "WARN":
                print(f"⚠️ COMMAND WARNING: {res['rationale']}")
                print(f"👉 Recommended replacement: {res['replacement']}")
                sys.exit(0)
            else:
                print(f"✅ Command is valid: {res['command']}")
                sys.exit(0)

    elif args.subcommand == "install-hook":
        target = Path(args.repo_path) if args.repo_path else None
        try:
            installed = install_hook(target, args.type)
            print(f"✅ Successfully installed {args.type} hook at: {installed}")
        except Exception as e:
            print(f"❌ Failed to install hook: {e}", file=sys.stderr)
            sys.exit(1)
        return

    elif args.subcommand == "configure":
        try:
            label = configure_key(provider=args.provider)
        except RuntimeError as exc:
            parser.exit(1, f"Error: {exc}\n")
        print(f"{label} API key saved in the system keyring.")
        return

    elif args.subcommand == "install-skill":
        if args.scope == "user" and args.dir:
            parser.error("--dir requires --scope project")
        base_dir = Path.home() if args.scope == "user" else Path(args.dir or Path.cwd())
        try:
            installed = install_agent_skill(args.scope, base_dir, force=args.force)
        except (RuntimeError, OSError) as exc:
            parser.exit(1, f"Error: {exc}\n")
        for path in installed:
            print(path)
        print("Restart your coding agent to discover the skill. The CLI and TypeSafe key are configured separately.")
        return

    # Only evaluation commands need Jev credentials.
    if args.subcommand in {"check", "audit-diff", "audit-plan"}:
        try:
            client = get_decision_client(provider=args.provider)
        except (RuntimeError, ValueError) as exc:
            parser.exit(1, f"Error: {exc}\n")

    if args.subcommand == "check":
        t0 = time.perf_counter()
        result = check_action(client, args.goal, args.plan, args.action, args.file, args.diff)
        dt = (time.perf_counter() - t0) * 1000.0

        status = result["status"]
        rationale = result["rationale"]
        metrics = result["metrics"]

        if not args.quiet:
            print_banner(status, args.goal, args.action, args.file, rationale, metrics)

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "check",
            "goal": args.goal,
            "action": args.action,
            "file": args.file,
            "status": status,
            "rationale": rationale,
            "metrics": metrics,
            "latency_ms": round(dt, 1)
        }
        log_telemetry(log_entry)

        if args.json:
            print(json.dumps(log_entry, indent=2))
        else:
            if status == "ALLOW":
                print(f"✅ GOVERNOR: Action approved ({metrics.get('alignment_choice', 'ok')}, risk: {metrics.get('risk_score', 0)})")
            else:
                print(f"🛑 GOVERNOR INTERVENTION [{status}]: {rationale}")

        if status.startswith("BLOCK") and not args.no_exit_code:
            sys.exit(1)
        else:
            sys.exit(0)

    elif args.subcommand == "audit-diff":
        t0 = time.perf_counter()
        target_dir = Path(args.dir) if args.dir else None
        try:
            result = audit_diff(client, args.goal, target_dir=target_dir, staged_only=args.staged)
        except RuntimeError as exc:
            parser.exit(1, f"Error: {exc}\n")
        dt = (time.perf_counter() - t0) * 1000.0

        status = result["status"]
        rationale = result["rationale"]
        metrics = result["metrics"]

        if not (args.quiet_allow and status == "ALLOW"):
            print_banner(status, args.goal, f"git diff ({'staged' if args.staged else 'working tree'})", "", rationale, metrics)

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "audit-diff",
            "goal": args.goal,
            "status": status,
            "rationale": rationale,
            "metrics": metrics,
            "latency_ms": round(dt, 1)
        }
        log_telemetry(log_entry)

        if args.json:
            print(json.dumps(log_entry, indent=2))
        else:
            if status == "ALLOW":
                if not args.quiet_allow:
                    print(f"✅ GOVERNOR: Git diff approved (risk: {metrics.get('risk_score', 0)})")
            else:
                print(f"🛑 GOVERNOR INTERVENTION [{status}]: {rationale}")

        if status.startswith("BLOCK") and not args.no_exit_code:
            sys.exit(1)
        else:
            sys.exit(0)

    elif args.subcommand == "audit-plan":
        t0 = time.perf_counter()
        result = audit_plan(client, args.goal, args.plan)
        dt = (time.perf_counter() - t0) * 1000.0
        result["latency_ms"] = round(dt, 1)

        if not args.json:
            print("=" * 68)
            print("📋 AGENT GOVERNOR PLAN AUDIT")
            print("=" * 68)
            print(f"Feasibility:     {result['feasibility'].upper()} (conf: {result['feasibility_confidence']})")
            print(f"Over-engineered: {result['is_over_engineered']} (P(yes))")
            print(f"Blast Radius:    {result['blast_radius_score']} / 2.0")
            print(f"Latency:         {result['latency_ms']} ms")
            print("=" * 68)
        else:
            print(json.dumps(result, indent=2))

        # Nonzero exit when the plan is not sound, so automation catches rejections
        if result["feasibility"] != "sound":
            sys.exit(1)

    elif args.subcommand == "report":
        if not LEDGER_FILE.exists():
            print("No ledger records found at", LEDGER_FILE)
            return

        entries = []
        with open(LEDGER_FILE) as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass

        blocks = [e for e in entries if e.get("status", "").startswith("BLOCK")]
        allows = [e for e in entries if e.get("status") == "ALLOW"]
        print("=" * 68)
        print(f"🛡️ AGENT GOVERNOR TELEMETRY REPORT ({len(entries)} events)")
        print("=" * 68)
        print(f"Allowed Actions:      {len(allows)}")
        print(f"Blocked Actions:      {len(blocks)}")
        if blocks:
            print("\nRecent Blocked Interventions:")
            for b in blocks[-6:]:
                act = b.get('action') or b.get('type', '')
                print(f"  • [{b['status']}] {act[:45]} (Goal: {b['goal'][:30]})")
        print("=" * 68)


if __name__ == "__main__":
    main()
