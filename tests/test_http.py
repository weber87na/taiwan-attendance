import http.client
import json
from datetime import datetime
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from attendance.server import AttendanceServer, csv_export
from attendance.store import Store, TZ


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = Store(str(Path(cls.temp.name) / "test.sqlite3"))
        with patch("attendance.store._now", return_value=datetime(2026, 1, 1, tzinfo=TZ)):
            cls.store.bootstrap("admin", "Test-password-1234")
        cls.server = AttendanceServer(("127.0.0.1", 0), cls.store)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        supplied = dict(headers or {})
        if body is not None:
            body = json.dumps(body)
            supplied.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=body, headers=supplied)
        response = connection.getresponse()
        raw = response.read().decode("utf-8-sig")
        result = (response.status, dict(response.getheaders()), json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw)
        connection.close()
        return result

    def login(self):
        status, headers, data = self.request("POST", "/api/login", {"username": "admin", "password": "Test-password-1234"})
        self.assertEqual(status, 200, data)
        self.assertNotIn("token", data)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        return {"Cookie": headers["Set-Cookie"].split(";")[0], "X-CSRF-Token": data["csrf_token"]}

    def test_session_and_csrf_and_logout(self):
        headers = self.login()
        status, _, data = self.request("GET", "/api/me", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["role"], "admin")
        self.assertEqual(self.request("POST", "/api/logout", {}, {"Cookie": headers["Cookie"]})[0], 403)
        self.assertEqual(self.request("POST", "/api/logout", {}, headers)[0], 200)
        self.assertEqual(self.request("GET", "/api/me", headers=headers)[0], 401)

    def test_cross_origin_and_host_rejected(self):
        self.assertEqual(self.request("POST", "/api/login", {"username": "admin", "password": "Test-password-1234"}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/health", headers={"Host": "evil.example"})[0], 403)

    def test_data_requires_login(self):
        for path in ("/api/punches", "/api/users", "/api/report.csv", "/api/audit"):
            self.assertEqual(self.request("GET", path)[0], 401)

    def test_calendar_and_calculators(self):
        headers = self.login()
        status, _, calendar = self.request("GET", "/api/calendar?year=2026&month=9", headers=headers)
        self.assertEqual(status, 200, calendar)
        self.assertEqual(len(calendar["days"]), 30)
        self.assertEqual(self.request("GET", "/api/calendar?year=2027&month=1", headers=headers)[0], 400)
        status, _, data = self.request("POST", "/api/calculate/overtime", {"hourly_wage": 240, "minutes": 120, "day_type": "weekday"}, headers)
        self.assertEqual(status, 200, data)
        self.assertEqual(float(data["pay"]), 640)
        status, _, data = self.request("POST", "/api/calculate/insurance", {"monthly_salary": 40000, "as_of": "2026-09-16"}, headers)
        self.assertEqual(status, 200, data)
        self.assertIn("employee", data)

    def test_static_security_and_no_file_traversal(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/../runtime/attendance.sqlite3")[0], 401)

    def test_nonfinite_and_nonobject_json_rejected(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        connection.request("POST", "/api/login", body='{"username":NaN}', headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        connection.close()
        self.assertEqual(self.request("POST", "/api/login", [1, 2])[0], 400)

    def test_csv_neutralizes_formulas(self):
        output = csv_export([{"name": "=HYPERLINK(\"bad\")", "minutes": 480}])
        self.assertIn("'=HYPERLINK", output)
        self.assertTrue(output.startswith("\ufeff"))

    def test_https_origin_enables_secure_cookie(self):
        server = AttendanceServer(("127.0.0.1", 0), self.store, public_origin="https://attendance.example.com")
        try:
            self.assertTrue(server.secure_cookie)
        finally:
            server.server_close()

    def test_schedule_edit_delete_and_cancel_require_csrf(self):
        headers = self.login()
        payload = {"user_id": 1, "date": "2026-10-01", "start": "09:00", "end": "18:00", "break_minutes": 60, "day_type": "workday"}
        status, _, schedule = self.request("POST", "/api/schedules", payload, headers)
        self.assertEqual(status, 200, schedule)
        path = f"/api/schedules/{schedule['id']}"
        for method in ("PUT", "PATCH", "DELETE"):
            self.assertEqual(self.request(method, path, payload, {"Cookie": headers["Cookie"]})[0], 403)
        payload["start"] = "08:30"
        payload["end"] = "17:30"
        self.assertEqual(self.request("PUT", path, payload, headers)[0], 200)
        self.assertEqual(self.request("DELETE", path, headers=headers)[0], 200)
        status, _, request = self.request("POST", "/api/requests", {"kind": "overtime", "start_at": "2026-10-01T18:00", "end_at": "2026-10-01T19:00", "requested_minutes": 60, "reason": "HTTP workflow test"}, headers)
        self.assertEqual(status, 200, request)
        self.assertEqual(self.request("DELETE", f"/api/requests/{request['id']}", {}, headers)[0], 200)


if __name__ == "__main__":
    unittest.main()
