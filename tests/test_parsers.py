import json
import os
import unittest

from resilience.parsers import parse_message
from resilience.events import EewReport, QuakeInfo

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class WolfxParserTest(unittest.TestCase):
    def test_forecast_fixture(self):
        ev = parse_message("wolfx", load("wolfx-eew-forecast.json"))
        self.assertIsInstance(ev, EewReport)
        self.assertEqual(ev.kind, "forecast")
        self.assertEqual(ev.event_id, "20261109140157")
        self.assertEqual(ev.serial, 6)
        self.assertTrue(ev.final)
        self.assertFalse(ev.cancelled)
        self.assertEqual(ev.magnitude, 4.8)
        self.assertEqual(ev.max_scale, 20)
        self.assertEqual(ev.hypocenter_name, "茨城県沖")

    def test_heartbeat_and_pong_ignored(self):
        self.assertIsNone(parse_message("wolfx", '{"type":"heartbeat","timestamp":"1"}'))
        self.assertIsNone(parse_message("wolfx", '{"type":"pong","timestamp":"1"}'))

    def test_cancel_report(self):
        payload = {"Title": "緊急地震速報（警報）", "EventID": "20261016123810",
                   "Serial": 99, "isWarn": True, "isCancel": True,
                   "AnnouncedTime": "2026/10/16 12:48:50",
                   "OriginTime": "2026/10/16 12:38:10", "Hypocenter": "千島列島",
                   "Latitude": 48.2, "Longitude": 153.4, "Depth": 140,
                   "Magnitude": 9.9, "MaxIntensity": "7", "WarnArea": []}
        ev = parse_message("wolfx", json.dumps(payload, ensure_ascii=False))
        self.assertTrue(ev.cancelled)
        self.assertEqual(ev.kind, "warning")


class P2pParserTest(unittest.TestCase):
    def test_warning_fixture(self):
        # The history API returns an array; WebSocket frames are single objects.
        ev = parse_message("p2p", json.dumps(json.loads(load("p2p-556-warning.json"))[0]))
        self.assertIsInstance(ev, EewReport)
        self.assertEqual(ev.kind, "warning")
        self.assertEqual(ev.event_id, "20261108010441")
        self.assertEqual(ev.serial, 1)
        self.assertFalse(ev.cancelled)
        self.assertEqual(ev.magnitude, 5.5)
        self.assertIn("愛知県西部", ev.areas)
        self.assertEqual(ev.areas["愛知県西部"], (45, 45))

    def test_detection(self):
        ev = parse_message("p2p", '{"code":554,"time":"2026/11/09 17:00:00","type":"Full"}')
        self.assertIsInstance(ev, EewReport)
        self.assertEqual(ev.kind, "detection")

    def test_cancel(self):
        payload = {"code": 556, "cancelled": True,
                   "issue": {"eventId": "20261016123810", "serial": "99",
                             "time": "2026/10/16 12:48:50"},
                   "areas": []}
        ev = parse_message("p2p", json.dumps(payload, ensure_ascii=False))
        self.assertTrue(ev.cancelled)
        self.assertEqual(ev.event_id, "20261016123810")

    def test_quake_info(self):
        payload = {"code": 551,
                   "earthquake": {"time": "2026/11/08 01:04:35", "maxScale": 55,
                                  "hypocenter": {"name": "愛知県東部", "magnitude": 5.5}},
                   "areas": [{"name": "愛知県西部", "maxScale": 45},
                             {"name": "愛知県東部", "maxScale": 55}]}
        ev = parse_message("p2p", json.dumps(payload))
        self.assertIsInstance(ev, QuakeInfo)
        self.assertEqual(ev.max_scale, 55)
        self.assertEqual(ev.areas, {"愛知県西部": 45, "愛知県東部": 55})

    def test_housekeeping_ignored(self):
        self.assertIsNone(parse_message("p2p", '{"code":555,"areas":[]}'))
        self.assertIsNone(parse_message("p2p", '{"code":561,"area":250}'))
        self.assertIsNone(parse_message("p2p", "not json"))


if __name__ == "__main__":
    unittest.main()
