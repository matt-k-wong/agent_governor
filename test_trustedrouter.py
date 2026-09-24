import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from typesafe_sdk import Choice, Noul, Score

import agent_governor


class TestTrustedRouterIntegration(unittest.TestCase):
    def test_trustedrouter_env_key_takes_effect_when_typesafe_is_absent(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "", "TRUSTEDROUTER_API_KEY": "sk-tr-test-key"}),
            patch.object(agent_governor.keyring, "get_password") as get_password,
        ):
            client = agent_governor.get_decision_client()
        get_password.assert_not_called()
        self.assertIsInstance(client, agent_governor.TrustedRouterClient)
        self.assertEqual(client.api_key, "sk-tr-test-key")

    def test_trustedrouter_keyring_resolution(self):
        def fake_get_password(service, account):
            if service == "trustedrouter" and account == "api-key":
                return "sk-tr-keyring-key"
            return None

        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "", "TRUSTEDROUTER_API_KEY": ""}),
            patch.object(agent_governor.keyring, "get_password", side_effect=fake_get_password),
        ):
            client = agent_governor.get_decision_client()
        self.assertIsInstance(client, agent_governor.TrustedRouterClient)
        self.assertEqual(client.api_key, "sk-tr-keyring-key")

    def test_explicit_provider_trustedrouter(self):
        with patch.dict(os.environ, {"TRUSTEDROUTER_API_KEY": "sk-tr-explicit"}):
            client = agent_governor.get_decision_client(provider="trustedrouter")
        self.assertIsInstance(client, agent_governor.TrustedRouterClient)
        self.assertEqual(client.api_key, "sk-tr-explicit")

    def test_explicit_provider_trustedrouter_missing_key(self):
        with (
            patch.dict(os.environ, {"TRUSTEDROUTER_API_KEY": ""}),
            patch.object(agent_governor.keyring, "get_password", return_value=None),
            self.assertRaisesRegex(RuntimeError, "No TrustedRouter API key found"),
        ):
            agent_governor.get_decision_client(provider="trustedrouter")

    def test_invalid_provider_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "Unknown provider"):
            agent_governor.get_decision_client(provider="invalid_provider")

    def test_trustedrouter_client_system_one_parsing(self):
        mock_response_data = {
            "model": "typesafe-ai/jev",
            "answers": {
                "alignment": {
                    "type": "choice",
                    "choice": "on_track",
                    "probabilities": {"on_track": 0.95, "drift_rabbit_hole": 0.05},
                },
                "is_scope_creep": {
                    "type": "noul",
                    "noul": 0.04,
                },
                "risk_severity": {
                    "type": "score",
                    "score": 0.25,
                    "probabilities": {"0": 0.8, "1": 0.15, "2": 0.05},
                },
            },
            "usage": {"inputTokens": 300, "outputTokens": 40},
            "trustedrouter": {
                "routing": {
                    "selected_model": "typesafe-ai/jev",
                    "selected_provider": "typesafe",
                },
            },
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        client = agent_governor.TrustedRouterClient(api_key="sk-tr-mock")
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            resp = client.system_one(
                state={"goal": "Fix bug"},
                questions={
                    "alignment": Choice(instructions="Evaluate alignment", criteria={"on_track": "good"}),
                    "is_scope_creep": Noul(instructions="Is creep"),
                    "risk_severity": Score(instructions="Rate risk", criteria=["Low", "Med", "High"]),
                },
            )

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-tr-mock")
        self.assertEqual(req.get_header("Content-type"), "application/json")

        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "typesafe-ai/jev")
        self.assertEqual(payload["questions"]["alignment"]["type"], "choice")
        self.assertEqual(payload["questions"]["is_scope_creep"]["type"], "noul")
        self.assertEqual(payload["questions"]["risk_severity"]["type"], "score")

        self.assertEqual(resp.answers["alignment"].choice, "on_track")
        self.assertEqual(resp.answers["alignment"].confidence, 0.95)
        self.assertEqual(resp.answers["is_scope_creep"].noul, 0.04)
        self.assertEqual(resp.answers["risk_severity"].score, 0.25)
        self.assertEqual(resp.answers["risk_severity"].confidence, 0.8)
        self.assertEqual(resp.routing["selected_provider"], "typesafe")

    def test_trustedrouter_client_http_error(self):
        client = agent_governor.TrustedRouterClient(api_key="sk-tr-mock")
        error = urllib.error.HTTPError(
            url="https://api.trustedrouter.com/api/alpha/decide",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(b'{"error": "invalid api key"}'),
        )
        with (
            patch("urllib.request.urlopen", side_effect=error),
            self.assertRaisesRegex(RuntimeError, "TrustedRouter request failed.*401.*invalid api key"),
        ):
            client.system_one(state="test", questions={})

    def test_configure_key_trustedrouter_explicit(self):
        with (
            patch("getpass.getpass", return_value="sk-tr-configured-key"),
            patch.object(agent_governor.keyring, "set_password") as set_pw,
        ):
            label = agent_governor.configure_key(provider="trustedrouter")
        set_pw.assert_called_once_with("trustedrouter", "api-key", "sk-tr-configured-key")
        self.assertEqual(label, "TrustedRouter")

    def test_configure_key_auto_detects_sk_tr_prefix(self):
        with (
            patch("getpass.getpass", return_value="sk-tr-auto-detected"),
            patch.object(agent_governor.keyring, "set_password") as set_pw,
        ):
            label = agent_governor.configure_key(provider="auto")
        set_pw.assert_called_once_with("trustedrouter", "api-key", "sk-tr-auto-detected")
        self.assertEqual(label, "TrustedRouter")

    def test_configure_key_auto_defaults_to_typesafe(self):
        with (
            patch("getpass.getpass", return_value="tsf_standard_key"),
            patch.object(agent_governor.keyring, "set_password") as set_pw,
        ):
            label = agent_governor.configure_key(provider="auto")
        set_pw.assert_called_once_with("typesafe-ai", "TYPESAFE_API_KEY", "tsf_standard_key")
        self.assertEqual(label, "TypeSafe")


if __name__ == "__main__":
    unittest.main()
