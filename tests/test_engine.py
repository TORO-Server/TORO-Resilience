import json
import os
import unittest

from resilience.config import Config
from resilience.engine import Engine
from resilience.parsers import parse_message

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class RecordingActions:
    def __init__(self):
        self.calls = []
        self.records = []

    def record(self, entry):
        self.records.append(entry)

    def notify_eew(self, key, state):
        self.calls.append("notify")

    def notify_cancel(self, key, state):
        self.calls.append("notify_cancel")

    def save_start(self, key, state):
        self.calls.append("save")

    def login_stop(self, key, state):
        self.calls.append("login_stop")

    def login_resume(self, key, state):
        self.calls.append("login_resume")

    def stop_recommended(self, key, info):
        self.calls.append("stop_recommended")


def make_engine():
    cfg = Config()
    cfg.host_area_names = ["愛知県西部"]
    actions = RecordingActions()
    return Engine(cfg, actions), actions


def wolfx_payload(**over):
    base = {"Title": "緊急地震速報（警報）", "EventID": "20261016123810",
            "Serial": 17, "isWarn": True, "isCancel": False, "isFinal": False,
            "AnnouncedTime": "2026/10/16 12:40:02",
            "OriginTime": "2026/10/16 12:38:10", "Hypocenter": "千島列島",
            "Latitude": 48.2, "Longitude": 153.4, "Depth": 140,
            "Magnitude": 9.9, "MaxIntensity": "7",
            "WarnArea": [{"Chiiki": "愛知県西部", "Shindo1": "5弱", "Shindo2": "5弱",
                          "Time": "12:45", "Type": "Warning"}]}
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


class EngineTest(unittest.TestCase):
    def test_p2p_warning_alone_stops_login(self):
        engine, actions = make_engine()
        with open(os.path.join(FIXTURES, "p2p-556-warning.json"), encoding="utf-8") as f:
            ev = parse_message("p2p", json.dumps(json.load(f)[0]))
        engine.handle_report(ev, now=100.0)
        # Host area 愛知県西部 has forecast 45 (5弱); P2P warning corroborates itself.
        self.assertEqual(actions.calls, ["notify", "save", "login_stop"])

    def test_wolfx_warning_alone_waits_for_corroboration(self):
        engine, actions = make_engine()
        ev = parse_message("wolfx", wolfx_payload())
        engine.handle_report(ev, now=100.0)
        self.assertEqual(actions.calls, ["notify", "save"])
        self.assertTrue(any(r.get("type") == "awaiting_corroboration" for r in actions.records))
        # P2P detection within the window corroborates.
        det = parse_message("p2p", '{"code":554,"time":"2026/10/16 12:40:05","type":"Full"}')
        engine.handle_report(det, now=110.0)
        self.assertEqual(actions.calls, ["notify", "save", "login_stop"])

    def test_dedupe(self):
        engine, actions = make_engine()
        ev = parse_message("wolfx", wolfx_payload())
        engine.handle_report(ev, now=100.0)
        engine.handle_report(ev, now=101.0)
        self.assertEqual(actions.calls, ["notify", "save"])

    def test_cancel_releases_login_stop(self):
        # Replay of the 2026-10-16 pattern: warning, corroboration, then a
        # cancel about nine minutes later releases only the login stop.
        engine, actions = make_engine()
        engine.handle_report(parse_message("wolfx", wolfx_payload()), now=100.0)
        det = parse_message("p2p", '{"code":554,"time":"2026/10/16 12:40:05","type":"Full"}')
        engine.handle_report(det, now=105.0)
        self.assertIn("login_stop", actions.calls)
        cancel = wolfx_payload(Serial=99, isCancel=True, Title="緊急地震速報（警報）")
        engine.handle_report(parse_message("wolfx", cancel), now=100.0 + 528.0)
        self.assertIn("notify_cancel", actions.calls)
        self.assertIn("login_resume", actions.calls)
        self.assertNotIn("stop_recommended", actions.calls)

    def test_forecast_scale4_saves_only(self):
        engine, actions = make_engine()
        payload = wolfx_payload(Title="緊急地震速報（予報）", isWarn=False,
                                Serial=3, MaxIntensity="4",
                                WarnArea=[{"Chiiki": "愛知県西部", "Shindo1": "4",
                                           "Shindo2": "4", "Time": "", "Type": "Forecast"}])
        engine.handle_report(parse_message("wolfx", payload), now=100.0)
        self.assertEqual(actions.calls, ["notify", "save"])

    def test_observed_strong_quake_recommends_stop(self):
        engine, actions = make_engine()
        engine.handle_report(parse_message("wolfx", wolfx_payload()), now=100.0)
        det = parse_message("p2p", '{"code":554,"time":"2026/10/16 12:40:05","type":"Full"}')
        engine.handle_report(det, now=105.0)
        quake = parse_message("p2p", json.dumps({
            "code": 551, "earthquake": {"time": "2026/10/16 12:38:10", "maxScale": 50,
                                        "hypocenter": {"name": "千島列島", "magnitude": 9.9}}}))
        engine.handle_quake(quake, now=400.0)
        self.assertIn("stop_recommended", actions.calls)
        # A late cancel must not resume logins after a stop recommendation.
        cancel = wolfx_payload(Serial=99, isCancel=True)
        engine.handle_report(parse_message("wolfx", cancel), now=500.0)
        self.assertNotIn("login_resume", actions.calls)

    def test_tier2_uses_host_area_not_national_max(self):
        engine, actions = make_engine()
        engine.handle_report(parse_message("wolfx", wolfx_payload()), now=100.0)
        det = parse_message("p2p", '{"code":554,"time":"2026/10/16 12:40:05","type":"Full"}')
        engine.handle_report(det, now=105.0)
        # National max 6弱, but the host area observed only 4: no stop.
        quake = parse_message("p2p", json.dumps({
            "code": 551, "earthquake": {"time": "2026/10/16 12:38:10", "maxScale": 60,
                                        "hypocenter": {"name": "千島列島", "magnitude": 9.9}},
            "areas": [{"name": "愛知県西部", "maxScale": 40},
                      {"name": "北海道東部", "maxScale": 60}]}))
        engine.handle_quake(quake, now=400.0)
        self.assertNotIn("stop_recommended", actions.calls)

    def test_training_ignored(self):
        engine, actions = make_engine()
        ev = parse_message("wolfx", wolfx_payload(isTraining=True))
        engine.handle_report(ev, now=100.0)
        self.assertEqual(actions.calls, [])


if __name__ == "__main__":
    unittest.main()
