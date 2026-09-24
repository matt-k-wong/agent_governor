import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import agent_governor


class TestAuditDiffRepositoryChecks(unittest.TestCase):
    def test_non_git_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "requires a Git repository"):
                agent_governor.audit_diff(Mock(), "Review changes", Path(temp_dir))

    def test_untracked_only_tree_is_audited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "new.py").write_text("print('hello')\n")
            answers = {
                "alignment": SimpleNamespace(choice="on_track", confidence=0.9),
                "is_test_tampering": SimpleNamespace(noul=0.0),
                "violates_invariants": SimpleNamespace(noul=0.0),
                "blast_radius": SimpleNamespace(score=0.0, confidence=0.9),
            }
            client = Mock()
            client.system_one.return_value.answers = answers

            result = agent_governor.audit_diff(client, "Add new.py", repo)

            client.system_one.assert_called_once()
            self.assertIn("new.py: +print('hello')", client.system_one.call_args.kwargs["state"]["compact_diff"])
            self.assertEqual(result["metrics"]["untracked_files_count"], 1)
            self.assertEqual(result["metrics"]["files_modified_count"], 1)

    @unittest.skipIf(os.name == "nt", "POSIX shell hook")
    def test_hook_fails_when_cli_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            hook = Path(agent_governor.install_hook(repo))
            result = subprocess.run(
                [str(hook)], capture_output=True, text=True,
                env={**os.environ, "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("not on PATH", result.stderr)


if __name__ == "__main__":
    unittest.main()
