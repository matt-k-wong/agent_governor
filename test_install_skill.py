import tempfile
import unittest
from pathlib import Path

import agent_governor


class TestSkillInstallation(unittest.TestCase):
    def test_packaged_skill_matches_source(self):
        source = Path(__file__).with_name("SKILL.md").read_text(encoding="utf-8")
        bundled = Path(agent_governor.__file__).with_name("agent_governor_skill") / "SKILL.md"
        self.assertEqual(bundled.read_text(encoding="utf-8"), source)

    def test_project_install_covers_supported_agents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            paths = agent_governor.install_agent_skill("project", base)
            self.assertEqual(
                {path.relative_to(base).as_posix() for path in paths},
                {
                    ".agents/skills/agent-governor/SKILL.md",
                    ".claude/skills/agent-governor/SKILL.md",
                    ".grok/skills/agent-governor/SKILL.md",
                },
            )
            self.assertTrue(all(path.exists() for path in paths))

    def test_user_install_does_not_replace_custom_skill_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            paths = agent_governor.install_agent_skill("user", base)
            self.assertEqual(len(paths), 4)
            paths[0].write_text("custom skill", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "--force"):
                agent_governor.install_agent_skill("user", base)
            self.assertEqual(paths[0].read_text(encoding="utf-8"), "custom skill")
            agent_governor.install_agent_skill("user", base, force=True)
            self.assertNotEqual(paths[0].read_text(encoding="utf-8"), "custom skill")


if __name__ == "__main__":
    unittest.main()
