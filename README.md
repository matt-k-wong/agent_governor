# Agent Governor

Agent Governor checks whether a coding agent's plan, proposed action, or Git diff stays aligned with a user's goal. It uses TypeSafe Jev for semantic judgments and local Python checks for known invalid commands, numbered-file collisions, and repository invariants.

## Fast Track: Let Your Agent Install It

If you're pairing with an AI coding agent (Claude Code, Codex, Antigravity, Grok, Cursor, etc.), you can streamline setup by pointing your agent directly at [`AGENTS.md`](AGENTS.md):

> *"Read AGENTS.md and install and configure Agent Governor for this workspace."*

Your agent will inspect the environment, install the package, set up your preferred credentials (`TYPESAFE_API_KEY` or `TRUSTEDROUTER_API_KEY`), run `agent-governor install-skill` to register the cross-agent skill, and verify the CLI.

## Manual Install

Requires Python 3.10 or newer and credentials for TypeSafe Jev (`audit-plan`, `check`, and `audit-diff`). You can connect directly to TypeSafe or route requests through [TrustedRouter](https://trustedrouter.com/docs).

```bash
python -m pip install "git+https://github.com/matt-k-wong/agent_governor.git"
```

From a cloned checkout, use `python -m pip install .` instead. The CLI must be installed in the environment your coding agent can access.

### Credentials

You can use either a TypeSafe or a TrustedRouter API key:

- **TypeSafe:** Set `TYPESAFE_API_KEY="your-key"` in your environment (from [TypeSafe Console](https://console.typesafe.ai/settings/keys)).
- **TrustedRouter:** Set `TRUSTEDROUTER_API_KEY="sk-tr-..."` in your environment (from [TrustedRouter](https://trustedrouter.com/)). Agent Governor calls the `/api/alpha/decide` endpoint using the `typesafe-ai/jev` model.

For example, in a POSIX shell:

```bash
export TYPESAFE_API_KEY="your-key"
# or
export TRUSTEDROUTER_API_KEY="sk-tr-your-key"
```

In PowerShell, use `$env:TYPESAFE_API_KEY = "your-key"` or `$env:TRUSTEDROUTER_API_KEY = "sk-tr-your-key"` for the current session.

As an alternative, run `agent-governor configure` (or `agent-governor configure --provider trustedrouter`) to enter the key at a hidden prompt and save it in your system keyring. Keys starting with `sk-tr-` are automatically saved to the TrustedRouter keyring. If both are present, the environment variable wins. Use `--provider typesafe` or `--provider trustedrouter` to explicitly select the backend (default: `auto`).

## Use with a coding agent

After installing the CLI, run:

```bash
agent-governor install-skill
```

This installs the same `agent-governor` skill for local Claude Code, Codex, Antigravity, and Grok sessions. Restart the agent, then ask it to use Agent Governor for a plan or diff audit. To share the skill with one repository instead, run `agent-governor install-skill --scope project --dir /path/to/repo` and commit the generated skill files. Existing customized copies are preserved unless you pass `--force`.

The skill tells an agent when and how to call the CLI. It does not intercept every agent action. Agents must have shell access to the installed CLI and access to `TYPESAFE_API_KEY` or the configured keyring. Cloud or hosted sessions need their own installation and credentials; a skill installed on your laptop is not automatically available there. See [agent integration details](docs/agent-integration.md).

## Use

```bash
# Audit a plan before starting
agent-governor audit-plan \
  --goal "Fix button padding on mobile" \
  --plan "Edit the button CSS, then check the layout"

# Check a proposed action
agent-governor check \
  --goal "Fix button padding on mobile" \
  --plan "Edit the button CSS, then check the layout" \
  --action "Edit button CSS" \
  --file "src/button.css"

# Audit changes in a Git repository
agent-governor audit-diff --goal "Fix button padding on mobile"

# Local checks and history
agent-governor lint-command "npm run typecheck"
agent-governor report
```

`check` and `audit-diff` exit with code 1 when they block an action. `audit-plan` exits with code 1 when the plan is not rated sound. `lint-command` exits with code 1 when it detects a failing gate. `report`, `lint-command`, and `install-hook` do not require an API key.

## Real-World Interventions: What Agent Governor Catches

The following examples come directly from real autonomous agent sessions recorded in the local Governor telemetry ledger:

### 1. Test Tampering / Cheating to Force Green CI (`BLOCK_TEST_TAMPERING`)
- **Goal:** `"Fix billing calculation edge case"`
- **Agent's Attempted Action:** Changing `expect(tax).toBe(10.50)` to `expect(tax).toBeGreaterThanOrEqual(0)` in `tests/billing.test.ts`.
- **Intervention:** **BLOCKED** (`tamper prob: 0.94`). Stopped the agent from weakening assertions to cheat test suites instead of fixing application code.
- **Another case:** When asked to `"Correct full-deck census"`, an agent attempted to replace an exact count assertion `assertEqual(counts[name], expected)` with `assertTrue(counts[name] >= 0)`. Blocked with `BLOCK_REPO_INVARIANT_VIOLATION` (prob: 0.97).

### 2. Scope Creep & Rabbit Holes (`BLOCK_SCOPE_CREEP`)
- **Goal:** `"Fix button padding on mobile log-squawk page"`
- **Agent's Attempted Action:** Editing `supabase/migrations/0320_fix_triggers.sql` to debug an unrelated database test failure encountered mid-task.
- **Intervention:** **BLOCKED** (`creep prob: 0.98`). Prevented a UI styling task from mutating database schemas.
- **Pre-Commit Diff Guard:** When an agent was tasked with `"card_row accessibility: slot semantics, focus restoration"`, `audit-diff` detected modifications across 15 unrelated files and blocked commit execution.

### 3. Breaking Business Logic to "Fix" Symptoms (`BLOCK_REPO_INVARIANT_VIOLATION`)
- **Goal:** `"Fix phantom win-distribution rows"`
- **Agent's Attempted Action:** "Change EVCalculator payouts so every quad category pays zero in all variants, making phantom rows disappear" in `video_poker_core.py`.
- **Intervention:** **BLOCKED** (prob: 0.82). The model attempted to silence the test failure by zeroing out valid payout tables.

### 4. Overwriting Append-Only Migrations (`BLOCK_MIGRATION_COLLISION`)
- **Goal:** `"Fix maintenance trigger"`
- **Agent's Attempted Action:** Edit `supabase/migrations/0007_maintenance.sql` when `0338` was already the latest migration.
- **Intervention:** **BLOCKED** (`"Migration 0007 already exists. Highest existing is 0338. Migrations must be strictly append-only."`).

### 5. Fake Gates & No-Op Commands (`BLOCK_FAKE_GATE`)
- **Goal:** `"Verify build after refactor"`
- **Agent's Verification Command:** `npx tsc --noEmit`
- **Intervention:** **BLOCKED** (`"Root tsconfig.json has 'files: []'. Running 'npx tsc --noEmit' checks NOTHING and exits 0 silently. Replace with: npm run typecheck (tsc -b --noEmit)"`).

### 6. Protecting Environment References (`BLOCK_REPO_INVARIANT_VIOLATION`)
- **Goal:** `"Update deployment target"`
- **Agent's Attempted Action:** "Modify .prod-ref with staging credentials" in `.prod-ref`.
- **Intervention:** **BLOCKED** (`"Direct modification of environment ref '.prod-ref' is forbidden. Project refs must not be altered."`).

## Data and configuration

The three Jev-backed commands send the supplied goal, plan or action, relevant repository rules, and sampled diff content to the TypeSafe API for evaluation. Verdicts and metrics are also written locally to `~/.agent_governor/ledger.jsonl`.

Agent Governor reads optional repository rules from `.governor.json` or selected sections of `CLAUDE.md`. Run `agent-governor install-hook` inside a Git repository to install a pre-commit audit of staged changes. The hook uses the installed `agent-governor` command.

See [AGENTS.md](AGENTS.md) for agent setup and troubleshooting, and [observed cases](docs/observed-cases.md) for interventions checked against the local ledger and code.

## Development

```bash
python -m pip install -e .
python -m unittest discover -v
```
