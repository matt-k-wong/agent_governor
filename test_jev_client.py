import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_governor


class TestJevClientConfiguration(unittest.TestCase):
    def test_environment_key_takes_precedence(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "environment-key"}),
            patch.object(agent_governor.keyring, "get_password") as get_password,
            patch.object(agent_governor, "TypeSafeClient") as client_type,
        ):
            agent_governor.get_typesafe_client()
        get_password.assert_not_called()
        client_type.assert_called_once_with(api_key="environment-key")

    def test_keyring_is_optional_when_environment_key_is_missing(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "", "TRUSTEDROUTER_API_KEY": ""}),
            patch.object(agent_governor.keyring, "get_password", return_value="saved-key"),
            patch.object(agent_governor, "TypeSafeClient") as client_type,
        ):
            agent_governor.get_typesafe_client()
        client_type.assert_called_once_with(api_key="saved-key")

    def test_missing_key_explains_both_setup_paths(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "", "TRUSTEDROUTER_API_KEY": ""}),
            patch.object(agent_governor.keyring, "get_password", return_value=None),
            self.assertRaisesRegex(RuntimeError, "configure.*TYPESAFE_API_KEY"),
        ):
            agent_governor.get_typesafe_client()

    def test_report_does_not_create_a_jev_client(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(agent_governor, "LEDGER_FILE", Path(temp_dir) / "ledger.jsonl"),
            patch.object(agent_governor, "get_typesafe_client") as get_client,
            patch.object(sys, "argv", ["agent-governor", "report"]),
        ):
            agent_governor.main()
        get_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
