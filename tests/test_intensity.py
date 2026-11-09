import unittest

from resilience.intensity import estimate_scale, haversine_km, host_scale
from resilience.events import EewReport


class IntensityTest(unittest.TestCase):
    def test_haversine(self):
        # Tokyo to Nagoya is roughly 260 km.
        d = haversine_km(35.68, 139.69, 35.18, 136.91)
        self.assertTrue(240 < d < 280)

    def test_near_large_quake_is_severe(self):
        scale = estimate_scale(magnitude=7.0, depth_km=30, epicentral_km=20)
        self.assertGreaterEqual(scale, 40)

    def test_far_small_quake_is_weak(self):
        scale = estimate_scale(magnitude=5.0, depth_km=40, epicentral_km=300)
        self.assertLessEqual(scale, 20)

    def test_area_takes_precedence(self):
        report = EewReport(source="wolfx", event_id="x", serial=1, kind="warning",
                           latitude=35.0, longitude=136.0, depth_km=10,
                           magnitude=5.0, areas={"対象地域": (45, 45)})
        result = host_scale(report, 35.0, 136.0, ["対象地域"])
        self.assertEqual(result, (45, "area"))

    def test_estimate_kind(self):
        report = EewReport(source="wolfx", event_id="x", serial=1, kind="forecast",
                           latitude=35.0, longitude=136.0, depth_km=30,
                           magnitude=7.0)
        result = host_scale(report, 35.1, 136.1, [])
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "estimate")

    def test_no_data_returns_none(self):
        report = EewReport(source="wolfx", event_id="x", serial=1, kind="forecast")
        self.assertIsNone(host_scale(report, None, None, []))


if __name__ == "__main__":
    unittest.main()
