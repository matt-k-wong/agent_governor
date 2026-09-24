# Coding agent integration

Install the Python CLI first (`python -m pip install .`), configure a TypeSafe or TrustedRouter key for Jev-backed commands, then run `agent-governor install-skill`. Restart the coding agent so it discovers the new skill.

| Agent | User-wide skill directory installed by the command | Project skill directory |
| --- | --- | --- |
| Codex | `~/.agents/skills/agent-governor/` | `.agents/skills/agent-governor/` |
| Claude Code | `~/.claude/skills/agent-governor/` | `.claude/skills/agent-governor/` |
| Antigravity 2.0 / IDE | `~/.gemini/config/skills/agent-governor/` | `.agents/skills/agent-governor/` |
| Antigravity CLI | `~/.gemini/antigravity-cli/skills/agent-governor/` | `.agents/skills/agent-governor/` |
| Grok Code | `~/.agents/skills/agent-governor/` | `.grok/skills/agent-governor/` |

These locations follow the [Codex skill guide](https://learn.chatgpt.com/docs/build-skills), [Claude Code skill guide](https://code.claude.com/docs/en/skills), [Antigravity skill guide](https://antigravity.google/docs/skills?app=antigravity), and [Grok skill guide](https://docs.x.ai/build/features/skills-plugins-marketplaces). `--scope project --dir /path/to/repo` writes all three project locations; `--scope user` (the default) writes the four distinct user locations.

## Check the integration

1. Confirm `agent-governor --help` works in the terminal the agent uses.
2. Confirm the skill appears in the agent's skill list, or explicitly invoke `agent-governor` by name in a prompt.
3. Ask for a local check such as `agent-governor lint-command "npm run typecheck"`. This needs no Jev key.
4. In a Git repository, ask for `agent-governor audit-diff --goal "<your goal>"` after setting up a TypeSafe or TrustedRouter key. The command sends diff context to Jev.

The skill provides instructions to the agent, so invocation still depends on the agent's tool access and behavior. It does not add universal tool hooks. Use `agent-governor install-hook` for a pre-commit audit in a Git repository. A hook runs only on Git commits and requires the CLI on its `PATH`.

User-wide skills stay on that computer. Hosted agents and cloud sessions need the skill and CLI installed in their own environment, plus access to a TypeSafe or TrustedRouter key. For teams, project skills can be committed with the repository; each runner still needs the CLI and credentials.
