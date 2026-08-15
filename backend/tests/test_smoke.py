import unittest

from app.health import health_status


class HealthStatusTest(unittest.TestCase):
    def test_health_status_reports_ok(self) -> None:
        self.assertEqual(health_status(), {"status": "ok"})
