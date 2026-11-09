import json
import os
import tempfile
import unittest

from resilience.actions import ActionHub, DiscordNotifier, IncidentLog
from resilience.config import Config


class LocalCommandTest(unittest.TestCase):
    def _hub(self, tmp, local_save):
        cfg = Config()
        cfg.incident_log_path = os.path.join(tmp, "incidents.jsonl")
        cfg.local_commands_on_save = local_save
        cfg.notify_discord = False
        log = IncidentLog(cfg.incident_log_path)
        return ActionHub(cfg, log, DiscordNotifier(None, log)), cfg

    def test_local_command_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub, cfg = self._hub(tmp, [["true"], ["false"]])
            hub.save_start("ev1", None)
            with open(cfg.incident_log_path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
            commands = [r for r in rows if r.get("type") == "local_command"]
            self.assertEqual([c["returncode"] for c in commands], [0, 1])
            self.assertEqual(commands[0]["command"], ["true"])

    def test_no_commands_no_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub, cfg = self._hub(tmp, [])
            hub.save_start("ev1", None)  # RCON disabled by default: records a skip
            with open(cfg.incident_log_path, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
            self.assertTrue(any(r.get("type") == "tier1_save_start" for r in rows))


if __name__ == "__main__":
    unittest.main()
