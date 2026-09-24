import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestLintCommandExitStatus(unittest.TestCase):
    def test_json_fail_returns_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("agent_governor.py")),
             "lint-command", "npx tsc --noEmit", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")
        self.assertEqual(result.returncode, 1, result.stderr)


class TestFailureMaskingDetection(unittest.TestCase):
    """Offline tests for failure-masking and no-op gate detection."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent))
        import agent_governor
        cls.gov = agent_governor

    def lint(self, cmd):
        return self.gov.lint_command(cmd)

    def test_or_true_is_masked(self):
        self.assertEqual(self.lint("npm test || true")["status"], "FAIL")

    def test_exit_zero_chain_is_masked(self):
        self.assertEqual(self.lint("pytest tests/; exit 0")["status"], "FAIL")

    def test_stderr_suppression_is_masked(self):
        self.assertEqual(self.lint("npm run typecheck 2>/dev/null")["status"], "FAIL")

    def test_bare_true_is_noop(self):
        self.assertEqual(self.lint("true")["status"], "FAIL")

    def test_empty_unittest_discovery_pattern(self):
        self.assertEqual(self.lint("python -m unittest discover -p 'census_*.py'")["status"], "FAIL")

    def test_valid_discovery_pattern_passes(self):
        res = self.lint("python -m unittest discover -p 'test_*.py'")
        self.assertNotEqual(res["status"], "FAIL")

    def test_valid_command_passes(self):
        self.assertEqual(self.lint("npm run typecheck")["status"], "PASS")


class TestCollisionGuardScope(unittest.TestCase):
    """BLOCK_COLLISION must only fire for numbered artifacts, not ordinary files."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parent))
        import agent_governor
        cls.gov = agent_governor

    def test_writing_existing_ordinary_file_allows(self):
        # agent_governor.py exists; a normal edit must not be a collision
        res = self.gov.check_unprobed_state(
            "Write the corrected function back to agent_governor.py", "agent_governor.py"
        )
        self.assertEqual(res["status"], "ALLOW")

    def test_creating_existing_numbered_plan_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_dir = Path(tmp) / "future-work"
            plan_dir.mkdir()
            (plan_dir / "PLAN-001.md").write_text("existing")
            res = self.gov.check_unprobed_state(
                "Create PLAN-001.md", "future-work/PLAN-001.md", repo_dir=Path(tmp)
            )
            self.assertEqual(res["status"], "BLOCK_COLLISION")


if __name__ == "__main__":
    unittest.main()
