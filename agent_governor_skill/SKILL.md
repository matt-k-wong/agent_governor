---
name: agent-governor
description: Check a coding agent's plan, proposed action, verification command, or Git diff against the user's goal. Use before broad edits, changes to tests or migrations, and commits when scope or integrity is uncertain.
---

# Agent Governor

Agent Governor is a local CLI. Jev evaluates ambiguous plan and change alignment; Python handles known command and repository checks. The user must install the CLI and configure a TypeSafe or TrustedRouter API key for Jev-backed commands. If `agent-governor` is unavailable, explain the setup problem; do not claim a check ran.

Use the user's actual goal and plan. Do not broaden or rephrase the goal merely to obtain an `ALLOW` verdict. Treat a verdict as evidence to inspect, not as a substitute for the user's instructions or the actual diff.

## Commands

Before a broad task, audit the proposed plan:

```bash
agent-governor audit-plan --goal "<user's goal>" --plan "<concrete steps>"
```

Before a sensitive action or a change to tests, ask whether the action fits the goal:

```bash
agent-governor check --goal "<user's goal>" --plan "<concrete steps>" --action "<next action>" --file "<target file>"
```

Before running a verification command, check for known fake gates:

```bash
agent-governor lint-command "<verification command>"
```

Before committing changes in a Git repository, review the working tree or staged diff:

```bash
agent-governor audit-diff --goal "<user's goal>"
agent-governor audit-diff --goal "<user's goal>" --staged
```

Exit code 1 means the plan or action was rejected, a fake gate was found, or the CLI could not complete the audit. Read the status and rationale before proceeding. A warning can still exit 0. If the governor blocks or warns, tell the user what it found and what correction you made. Do not hide a block with `--no-exit-code`.

`audit-diff` reports the repository's current changes, which may include work from another task. Inspect `git status` and the diff before attributing all changes to the current agent. The skill guides agent behavior; it does not install automatic tool-call interception. `agent-governor install-hook` separately installs a Git pre-commit check.
