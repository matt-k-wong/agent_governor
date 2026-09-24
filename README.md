# Agent Governor

Agent Governor checks whether a coding agent's plan, proposed action, or Git diff stays aligned with a user's goal. It uses TypeSafe Jev for semantic judgments and local Python checks for known invalid commands, numbered-file collisions, and repository invariants.

## Install

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

## Data and configuration

The three Jev-backed commands send the supplied goal, plan or action, relevant repository rules, and sampled diff content to the TypeSafe API for evaluation. Verdicts and metrics are also written locally to `~/.agent_governor/ledger.jsonl`.

Agent Governor reads optional repository rules from `.governor.json` or selected sections of `CLAUDE.md`. Run `agent-governor install-hook` inside a Git repository to install a pre-commit audit of staged changes. The hook uses the installed `agent-governor` command.

See [AGENTS.md](AGENTS.md) for agent setup and troubleshooting, and [observed cases](docs/observed-cases.md) for interventions checked against the local ledger and code.

## Development

```bash
python -m pip install -e .
python -m unittest discover -v
```
