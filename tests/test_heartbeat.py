import os
import tempfile
import time
import unittest

from resilience.heartbeat import heartbeat_status, write_heartbeat


class HeartbeatTest(unittest.TestCase):
    def test_write_and_ok(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hb.json")
            write_heartbeat(path)
            status = heartbeat_status(path, stale_s=180.0)
            self.assertEqual(status["state"], "ok")
            self.assertLess(status["age_s"], 5)

    def test_stale(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hb.json")
            payload = write_heartbeat(path)
            status = heartbeat_status(path, stale_s=180.0,
                                      now_epoch=payload["epoch"] + 181)
            self.assertEqual(status["state"], "stale")

    def test_missing(self):
        status = heartbeat_status("/nonexistent/hb.json", stale_s=180.0)
        self.assertEqual(status["state"], "missing")


if __name__ == "__main__":
    unittest.main()
