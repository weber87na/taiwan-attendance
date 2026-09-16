import hashlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from attendance.store import DomainError, Store, TZ


PASSWORD = "test-password-1234"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "attendance.db")
        self.store = Store(self.path)
        self.admin = self.store.bootstrap("admin", PASSWORD)
        self.employee = self.call(self.admin, "POST", "/api/users", {
            "username": "employee", "name": "測試員工", "password": PASSWORD,
            "hire_date": "2020-09-01", "monthly_salary": 40000})
        self.manager = self.call(self.admin, "POST", "/api/users", {
            "username": "manager", "name": "測試主管", "password": PASSWORD,
            "role": "manager", "hire_date": "2020-01-01"})

    def call(self, actor, method, path, data=None, query=None):
        return self.store.handle(actor, method, path, data or {}, query or {})

    def assert_error(self, status, function, *args, **kwargs):
        with self.assertRaises(DomainError) as caught:
            function(*args, **kwargs)
        self.assertEqual(status, caught.exception.status)
        return str(caught.exception)

    def clock(self, at, kind, actor=None):
        with patch("attendance.store._now", return_value=datetime.fromisoformat(at).replace(tzinfo=TZ)):
            return self.store.clock(actor or self.employee, kind)

    def schedule(self, on="2026-09-15", start="09:00", end="18:00", break_minutes=60):
        return self.call(self.admin, "POST", "/api/schedules", {
            "user_id": self.employee["id"], "date": on, "start": start, "end": end,
            "break_minutes": break_minutes, "day_type": "workday"})

    def leave(self, start, end, minutes, kind="personal"):
        return self.call(self.employee, "POST", "/api/requests", {
            "kind": "leave", "leave_type": kind, "start_at": start, "end_at": end,
            "requested_minutes": minutes, "reason": "測試請假"})

    def correction(self, at, kind, target=None):
        data = {"kind": "correction", "correction_kind": kind, "correction_at": at,
                "reason": "漏卡／時間更正"}
        if target:
            data["target_punch_id"] = target
        return self.call(self.employee, "POST", "/api/requests", data)

    def review(self, request, actor=None, decision="approved"):
        return self.call(actor or self.admin, "POST", f"/api/requests/{request['id']}/review", {"decision": decision})

    def report(self, month="2026-09"):
        return self.call(self.employee, "GET", "/api/report", query={"month": month})["rows"]

    def test_accounts_sessions_and_password_rotation(self):
        self.assert_error(409, self.store.bootstrap, "another", PASSWORD)
        self.assert_error(400, self.call, self.admin, "POST", "/api/users", {
            "username": "short", "name": "short", "password": "short"})
        login = self.store.login("EMPLOYEE", PASSWORD)
        self.assertEqual(self.employee["id"], self.store.user_for_token(login["token"])["id"])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            stored = conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
            self.assertEqual(hashlib.sha256(login["token"].encode()).hexdigest(), stored)
            self.assertNotEqual(login["token"], stored)
            salt, digest = conn.execute("SELECT password_salt,password_hash FROM users WHERE id=?", (self.employee["id"],)).fetchone()
            self.assertEqual(len(salt), 32)
            self.assertNotEqual(digest, PASSWORD)
        self.call(self.employee, "POST", "/api/password", {"current_password": PASSWORD, "new_password": "replacement-password"})
        self.assert_error(401, self.store.user_for_token, login["token"])
        self.assert_error(401, self.store.login, "employee", PASSWORD)
        new_login = self.store.login("employee", "replacement-password")
        self.store.logout(new_login["token"])
        self.assert_error(401, self.store.user_for_token, new_login["token"])

    def test_expiry_and_login_throttle(self):
        now = datetime(2026, 9, 15, 9, tzinfo=TZ)
        with patch("attendance.store._now", return_value=now):
            login = self.store.login("employee", PASSWORD)
            for _ in range(5):
                self.assert_error(401, self.store.login, "missing", "wrong-password")
            self.assert_error(429, self.store.login, "missing", PASSWORD)
        with patch("attendance.store._now", return_value=now + timedelta(hours=13)):
            self.assert_error(401, self.store.user_for_token, login["token"])

    def test_role_scope_and_privilege_escalation(self):
        for endpoint in ("punches", "schedules", "requests", "report"):
            self.assert_error(403, self.call, self.employee, "GET", "/api/"+endpoint, query={"user_id": self.admin["id"]})
        self.assert_error(403, self.call, self.employee, "GET", "/api/audit")
        users = self.call(self.employee, "GET", "/api/users")
        self.assertEqual([self.employee["id"]], [row["id"] for row in users])
        self.assert_error(403, self.call, self.manager, "POST", "/api/users", {
            "username": "attacker", "name": "attacker", "password": PASSWORD, "role": "admin"})
        # Do not trust a stale or forged role in a caller's dictionary.
        forged = dict(self.employee, role="admin")
        self.assert_error(403, self.call, forged, "GET", "/api/audit")

    def test_clock_sequence_and_exact_work_minutes(self):
        self.assert_error(409, self.store.clock, self.employee, "out")
        self.assert_error(400, self.call, self.employee, "POST", "/api/clock", {"kind": "in", "occurred_at": "2000-01-01"})
        self.clock("2026-09-15T09:00:00", "in")
        self.clock("2026-09-15T13:00:00", "break_start")
        self.clock("2026-09-15T14:00:00", "break_end")
        self.clock("2026-09-15T18:00:00.500000", "out")
        row = self.report()[0]
        self.assertAlmostEqual(480 + .5/60, row["work_minutes"])
        self.assertEqual(60, row["break_minutes"])
        self.assertEqual(4, len(self.store.punches(self.employee, "2026-09")))

    def test_schedule_break_is_not_automatically_deducted(self):
        self.schedule()
        self.clock("2026-09-15T09:00:00", "in")
        self.clock("2026-09-15T18:00:00", "out")
        row = self.report()[0]
        self.assertEqual(540, row["work_minutes"])
        self.assertEqual(0, row["break_minutes"])
        self.assertEqual(480, row["scheduled_minutes"])
        self.assertTrue(row["issues"])

    def test_short_break_does_not_reset_four_hour_rest_warning(self):
        self.clock("2026-09-15T09:00:00", "in")
        self.clock("2026-09-15T13:00:00", "break_start")
        self.clock("2026-09-15T13:01:00", "break_end")
        self.clock("2026-09-15T17:01:00", "out")
        row = self.report()[0]
        self.assertEqual(480, row["work_minutes"])
        self.assertEqual("review_required", row["status"])
        self.assertIn("30 分鐘", row["issues"][0])

    def test_overnight_and_incomplete_report(self):
        self.clock("2026-08-31T22:00:00", "in")
        self.clock("2026-09-01T06:00:00", "out")
        self.assertEqual(480, self.report("2026-08")[0]["work_minutes"])
        self.assertEqual([], self.report("2026-09"))
        self.clock("2026-09-15T09:00:00", "in")
        self.assertIsNone(self.report()[0]["work_minutes"])
        self.clock("2026-09-16T10:00:00", "out")
        self.assertIsNone(self.report()[0]["work_minutes"])

    def test_concurrent_duplicate_clock(self):
        def attempt(_):
            try:
                return self.store.clock(self.employee, "in")["kind"]
            except DomainError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(attempt, range(2)))
        self.assertCountEqual(["in", 409], outcomes)

    def test_leave_capacity_reservations_and_approval(self):
        self.schedule()
        first = self.leave("2026-09-15T09:00", "2026-09-15T13:00", 240)
        self.assert_error(409, self.leave, "2026-09-15T13:00", "2026-09-15T18:00", 300)
        second = self.leave("2026-09-15T13:00", "2026-09-15T18:00", 240)
        self.review(first)
        self.review(second)
        self.assertEqual(480, self.report()[0]["leave_minutes"])
        self.assert_error(409, self.review, first)
        self.assert_error(409, self.call, self.admin, "DELETE", "/api/schedules/1")

    def test_leave_requires_schedule_and_explicit_net_minutes(self):
        self.assert_error(400, self.leave, "2026-09-15T09:00", "2026-09-15T18:00", 480)
        self.schedule()
        self.assert_error(400, self.leave, "2026-09-15T09:00", "2026-09-15T18:00", 540)
        self.assert_error(400, self.call, self.employee, "POST", "/api/requests", {
            "kind": "leave", "leave_type": "personal", "start_at": "2026-09-15T09:00", "end_at": "2026-09-15T18:00", "reason": "test"})

    def test_leave_year_boundary_and_cancellation(self):
        self.schedule("2026-12-31")
        self.schedule("2027-01-01")
        self.assert_error(400, self.leave, "2026-12-31T09:00", "2027-01-01T18:00", 960)
        request = self.leave("2026-12-31T09:00", "2026-12-31T18:00", 480)
        self.call(self.employee, "DELETE", f"/api/requests/{request['id']}")
        self.assertEqual("pending", self.leave("2026-12-31T09:00", "2026-12-31T18:00", 480)["status"])

    def test_annual_quota_and_anniversary_boundary(self):
        junior = self.call(self.admin, "POST", "/api/users", {
            "username": "junior", "name": "新人", "password": PASSWORD, "hire_date": "2026-03-01"})
        for on in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
            self.call(self.admin, "POST", "/api/schedules", {
                "user_id": junior["id"], "date": on, "start": "09:00", "end": "18:00", "break_minutes": 60})
        def request(on):
            return self.call(junior, "POST", "/api/requests", {
                "kind": "leave", "leave_type": "annual", "start_at": on+"T09:00", "end_at": on+"T18:00",
                "requested_minutes": 480, "reason": "新人半年特休"})
        for on in ("2026-09-01", "2026-09-02", "2026-09-03"):
            request(on)
        self.assert_error(409, request, "2026-09-04")
        self.schedule("2026-08-31")
        self.schedule("2026-09-01")
        self.assert_error(400, self.leave, "2026-08-31T09:00", "2026-09-01T18:00", 960, "annual")

    def test_menstrual_leave_remains_available_after_sick_quota_exhausted(self):
        # Synthetic schedules isolate quota accounting from holiday scheduling.
        for day in range(1, 31):
            self.schedule(f"2026-01-{day:02d}")
        self.leave("2026-01-01T09:00", "2026-01-30T18:00", 30*480, "sick")
        for month in (2, 3, 4, 5):
            on = f"2026-{month:02d}-16"
            self.schedule(on)
            request = self.leave(on+"T09:00", on+"T18:00", 480, "menstrual")
            self.assertEqual("pending", request["status"])
        self.schedule("2026-06-16")
        self.assert_error(409, self.leave, "2026-06-16T09:00", "2026-06-16T18:00", 480, "sick")

    def test_correction_approval_and_raw_preservation(self):
        original = self.clock("2026-09-15T09:00:00", "in")
        self.clock("2026-09-15T18:00:00", "out")
        request = self.correction("2026-09-15T08:59:30", "in", original["id"])
        self.review(request)
        effective = self.store.punches(self.employee, "2026-09")
        self.assertEqual(2, len(effective))
        self.assertEqual("correction", effective[0]["source"])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(3, conn.execute("SELECT count(*) FROM punches").fetchone()[0])
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE punches SET kind='out' WHERE id=?", (original["id"],))
        self.assertAlmostEqual(540.5, self.report()[0]["work_minutes"])

    def test_batch_correction_restores_whole_historical_shift(self):
        self.clock("2026-09-15T09:00:00", "in")
        self.clock("2026-09-15T18:00:00", "out")
        first = self.correction("2026-09-14T09:00:00", "in")
        last = self.correction("2026-09-14T18:00:00", "out")
        self.assert_error(409, self.review, first)
        self.assert_error(409, self.review, last)
        result = self.call(self.admin, "POST", "/api/requests/review-batch", {
            "request_ids": [first["id"], last["id"]], "decision": "approved"})
        self.assertEqual(2, len(result["requests"]))
        self.assertEqual([540, 540], [row["work_minutes"] for row in self.report()])
        self.assert_error(409, self.call, self.admin, "POST", "/api/requests/review-batch", {
            "request_ids": [first["id"], last["id"]], "decision": "approved"})

    def test_concurrent_reviews_and_self_approval(self):
        request = self.call(self.employee, "POST", "/api/requests", {
            "kind": "overtime", "start_at": "2026-09-15T18:00", "end_at": "2026-09-15T19:00",
            "requested_minutes": 60, "reason": "加班"})
        def approve(actor):
            try:
                return self.review(request, actor)["status"]
            except DomainError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(approve, [self.admin, self.manager]))
        self.assertCountEqual(["approved", 409], outcomes)
        own = self.call(self.manager, "POST", "/api/requests", {
            "kind": "overtime", "start_at": "2026-09-15T18:00", "end_at": "2026-09-15T19:00",
            "requested_minutes": 60, "reason": "主管加班"})
        self.assert_error(403, self.review, own, self.manager)

    def test_audit_append_only_and_malformed_input(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM audit")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE audit SET action='tampered'")
        for value in ([], {}, 1, None):
            self.assert_error(400, self.call, self.employee, "POST", "/api/clock", {"kind": value})
            self.assert_error(400, self.call, self.employee, "POST", "/api/requests", {"kind": value})
        self.assert_error(400, self.call, self.employee, "GET", "/api/report", query={"month": "9999-12"})
        self.assert_error(400, self.call, self.admin, "POST", "/api/requests/" + "9"*100 + "/review", {"decision": "approved"})


if __name__ == "__main__":
    unittest.main()
