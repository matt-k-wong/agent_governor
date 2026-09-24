# Agent Governor: guide for coding agents and maintainers

This file is the starting point when an agent is asked to install, use, debug, or change Agent Governor. Read `README.md` for the user-facing commands and `SKILL.md` for when to invoke them.

## What runs where

- `agent_governor.py` contains the CLI, deterministic checks, Jev questions, decision thresholds, and local ledger writer.
- `agent_governor.py` contains the CLI, deterministic checks, Jev questions, decision thresholds, and local ledger writer.
- Jev evaluation is supported directly via TypeSafe or routed through TrustedRouter (`typesafe-ai/jev`).
- `typesafe-sdk` is an installed Python dependency. `check`, `audit-plan`, and `audit-diff` send structured decision requests to TypeSafe or TrustedRouter. There is no local model and no dependency on the maintainer's `~/jev` directory.
- `lint-command`, `report`, and `install-hook` do not call Jev and need no API key.
- The CLI writes verdict records to `~/.agent_governor/ledger.jsonl`. The API key must never appear in that ledger, command arguments, tests, or Git history.

## From a fresh checkout

1. Use Python 3.10 or newer. Run `python -m pip install .` from this directory. For development, use `python -m pip install -e .`.
2. Set `TYPESAFE_API_KEY` or `TRUSTEDROUTER_API_KEY` in the process environment on any operating system. Alternatively, run `agent-governor configure` (or `agent-governor configure --provider trustedrouter`) to save a key in the system keyring. Environment variables take precedence.
3. Run `agent-governor install-skill` to make the skill available to local Claude Code, Codex, Antigravity, and Grok sessions. See `docs/agent-integration.md` for locations and project installation.
4. Run `agent-governor --help`, then `agent-governor lint-command "npm run typecheck"` to confirm the CLI starts without contacting Jev.
5. In a Git repository, run `agent-governor audit-diff --goal "<the user's actual goal>"` to exercise the Jev path. This sends diff context to TypeSafe or TrustedRouter and may use paid API access.

Do not paste an API key into a command line, issue, test fixture, or chat. `configure` uses a hidden prompt. If a keyring is unavailable, use the environment variable.

## Common problems

| Symptom | Check | Fix |
| --- | --- | --- |
| `agent-governor: command not found` | `python -m pip show agent-governor` and whether the Python scripts directory is on `PATH` | Activate the environment where it was installed, or install into the intended environment. |
| Agent cannot find the skill | Check the agent's skill list and the directories in `docs/agent-integration.md` | Run `agent-governor install-skill` in the environment where that agent runs, then restart it. |
| `No TypeSafe API key found` | Whether the running process received `TYPESAFE_API_KEY` | Set that variable, or run `agent-governor configure` on a machine with a working keyring. |
| Keyring error on a headless machine | Whether `TYPESAFE_API_KEY` is set | Use the environment variable; it bypasses the keyring. |
| Jev API/auth error | Key validity, API access, and network reachability | Check the TypeSafe console and retry. Local-only commands can still run. |
| `audit-diff` finds nothing | Run `git status --short` in the target repository | Stage or modify the intended files; use `--staged` to audit staged changes. Supply `--dir` if invoking from elsewhere. |
| Hook rejects a commit because it cannot find the CLI | `command -v agent-governor` from the Git hook environment and `.git/hooks/pre-commit` | Activate the installed environment or put its scripts directory on the hook's `PATH`. The hook fails closed when the command is absent. |
| Unexpected block | Read the status, rationale, and original goal | Check whether the plan and goal accurately describe the authorized work. Inspect the actual diff before changing or retrying anything. |

## Development and verification

Run `python -m unittest discover -v`. Tests must use mock clients and keys; routine tests must not call the live API. A change to Jev questions or decision thresholds needs a focused regression case with representative answers. A change to the CLI or packaging should also be checked through an installed console script.

Keep local rules deterministic. Use Jev for ambiguous judgments about plan alignment, test weakening, and blast radius. Code owns blocking thresholds and side effects. Do not turn a Jev score alone into an irreversible action.

The current ledger records verdicts, not whether an agent obeyed a block or whether a fix landed. When documenting a success story, corroborate it with a follow-up action and the resulting code or tests. Evaluation scenarios should be labeled as evaluations. See `docs/observed-cases.md`.
