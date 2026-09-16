"""Transactional attendance storage. All public timestamps use Asia/Taipei (UTC+8).

Raw punches and audit entries are append-only. Approved corrections append a new
event and optionally supersede an existing event; they never rewrite its time.
Payroll exports contain measured attendance, not a legal determination of wages.
"""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROLES = {"employee", "manager", "admin"}
KINDS = {"in", "out", "break_start", "break_end"}
DAY_TYPES = {"workday", "rest_day", "regular_day_off", "holiday"}
PASSWORD_ITERATIONS = 310_000
SESSION_HOURS = 12


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now():
    return datetime.now(TZ)


def _iso(value):
    return value.astimezone(TZ).isoformat(timespec="microseconds")


def _date(value, field="日期"):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError()
        result = date.fromisoformat(value)
        if not 1900 <= result.year <= 2199:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise DomainError(f"{field}須為有效 YYYY-MM-DD") from None


def _timestamp(value, field="時間"):
    try:
        if not isinstance(value, str):
            raise ValueError()
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=TZ)
        result = result.astimezone(TZ)
        if not 1900 <= result.year <= 2199:
            raise ValueError()
        return result
    except (ValueError, TypeError, OverflowError):
        raise DomainError(f"{field}須為有效 ISO 日期時間（未附時區視為臺灣時間）") from None


def _int(value, field, low=0, high=2_147_483_647):
    if isinstance(value, bool):
        raise DomainError(f"{field}須為整數")
    try:
        result = int(value)
        if str(result) != str(value) or not low <= result <= high:
            raise ValueError()
        return result
    except (TypeError, ValueError, OverflowError):
        raise DomainError(f"{field}須介於 {low} 到 {high} 的整數") from None


def _text(value, field, limit=1000, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise DomainError(f"{field}須為{'非空白' if required else ''}文字，最長 {limit} 字")
    return value.strip()


def _password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 256:
        raise DomainError("密碼長度須為 12 至 256 個字元")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
    return salt, digest


def _verify(value, salt, expected):
    if not isinstance(value, str) or len(value) > 256:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", value.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS).hex()
    return hmac.compare_digest(actual, expected)


def _add_months(value, months):
    absolute = value.year * 12 + value.month - 1 + months
    year, month = divmod(absolute, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _annual_period(hire, on):
    six_months, one_year = _add_months(hire, 6), _add_months(hire, 12)
    if on < six_months:
        return hire, six_months
    if on < one_year:
        return six_months, one_year
    years = on.year - hire.year
    if on < _add_months(hire, years * 12):
        years -= 1
    return _add_months(hire, years * 12), _add_months(hire, (years + 1) * 12)


class Store:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        if self.db_path == ":memory:":
            raise ValueError("Use a temporary database file; each transaction has an isolated connection")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                  name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('employee','manager','admin')),
                  hire_date TEXT NOT NULL, monthly_salary INTEGER NOT NULL DEFAULT 0,
                  active INTEGER NOT NULL DEFAULT 1, password_salt TEXT NOT NULL,
                  password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                  expires_at TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS login_attempts (
                  username TEXT PRIMARY KEY, failures INTEGER NOT NULL, blocked_until TEXT,
                  last_attempt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                  kind TEXT NOT NULL CHECK(kind IN ('leave','correction','overtime')),
                  status TEXT NOT NULL DEFAULT 'pending', start_at TEXT, end_at TEXT,
                  leave_type TEXT, requested_minutes INTEGER NOT NULL DEFAULT 0,
                  reason TEXT NOT NULL, correction_kind TEXT, correction_at TEXT,
                  target_punch_id INTEGER, reviewer_id INTEGER REFERENCES users(id),
                  review_comment TEXT, created_at TEXT NOT NULL, reviewed_at TEXT);
                CREATE TABLE IF NOT EXISTS punches (
                  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                  kind TEXT NOT NULL CHECK(kind IN ('in','out','break_start','break_end')),
                  occurred_at TEXT NOT NULL, source TEXT NOT NULL,
                  request_id INTEGER UNIQUE REFERENCES requests(id),
                  supersedes INTEGER UNIQUE REFERENCES punches(id), created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS punches_user_time ON punches(user_id,occurred_at,id);
                CREATE TABLE IF NOT EXISTS schedules (
                  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                  date TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                  break_minutes INTEGER NOT NULL DEFAULT 0, day_type TEXT NOT NULL,
                  holiday_name TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id),
                  updated_at TEXT NOT NULL, UNIQUE(user_id,date));
                CREATE TABLE IF NOT EXISTS audit (
                  id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL,
                  entity_type TEXT NOT NULL, entity_id TEXT, detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS punches_no_update BEFORE UPDATE ON punches
                  BEGIN SELECT RAISE(ABORT, 'punches are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS punches_no_delete BEFORE DELETE ON punches
                  BEGIN SELECT RAISE(ABORT, 'punches are append-only'); END;
            """)

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _user(row):
        return {key: row[key] for key in ("id", "username", "name", "role", "hire_date", "monthly_salary", "active")}

    @staticmethod
    def _audit(conn, actor_id, action, entity_type, entity_id=None, detail=None):
        conn.execute("INSERT INTO audit(actor_id,action,entity_type,entity_id,detail,created_at) VALUES(?,?,?,?,?,?)",
                     (actor_id, action, entity_type, str(entity_id) if entity_id is not None else None,
                      json.dumps(detail or {}, ensure_ascii=False), _iso(_now())))

    def _create_user(self, conn, data, actor=None):
        username = _text(data.get("username"), "帳號", 80)
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,80}", username):
            raise DomainError("帳號須為 3–80 碼英文、數字或 _.@-")
        name = _text(data.get("name"), "姓名", 80)
        role = data.get("role", "employee")
        if not isinstance(role, str) or role not in ROLES or (actor and actor["role"] != "admin" and role != "employee"):
            raise DomainError("僅管理員可以建立主管或管理員", 403)
        hire = _date(data.get("hire_date", _now().date().isoformat()), "到職日")
        salary = _int(data.get("monthly_salary", 0), "月薪", high=100_000_000)
        salt, digest = _password(data.get("password"))
        try:
            cursor = conn.execute("INSERT INTO users(username,name,role,hire_date,monthly_salary,password_salt,password_hash,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                  (username, name, role, str(hire), salary, salt, digest, _iso(_now())))
        except sqlite3.IntegrityError:
            raise DomainError("帳號已存在", 409) from None
        self._audit(conn, actor["id"] if actor else cursor.lastrowid, "user.created", "user", cursor.lastrowid,
                    {"username": username, "role": role})
        return self._user(conn.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())

    def bootstrap(self, username, password, name="管理員"):
        with self._transaction() as conn:
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise DomainError("系統已初始化；請使用現有管理員建立帳號", 409)
            return self._create_user(conn, {"username": username, "password": password, "name": name, "role": "admin"})

    def login(self, username, password):
        username = _text(username, "帳號", 80).lower()
        error = None
        result = None
        with self._transaction() as conn:
            now = _now()
            attempts = conn.execute("SELECT * FROM login_attempts WHERE username=?", (username,)).fetchone()
            if attempts and attempts["blocked_until"] and _timestamp(attempts["blocked_until"]) > now:
                raise DomainError("登入失敗次數過多，請 15 分鐘後再試", 429)
            row = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
            # Unknown and disabled accounts have the same response and hashing cost.
            valid = _verify(password, row["password_salt"] if row else "00" * 16,
                            row["password_hash"] if row else "00" * 32)
            if not valid or not row or not row["active"]:
                failures = (attempts["failures"] if attempts and
                            _timestamp(attempts["last_attempt"]) > now - timedelta(minutes=15) else 0) + 1
                blocked_until = _iso(now + timedelta(minutes=15)) if failures >= 5 else None
                conn.execute("INSERT INTO login_attempts VALUES(?,?,?,?) ON CONFLICT(username) DO UPDATE SET failures=excluded.failures,blocked_until=excluded.blocked_until,last_attempt=excluded.last_attempt",
                             (username, failures, blocked_until, _iso(now)))
                self._audit(conn, None, "session.failed", "session", detail={"username": username})
                error = DomainError("帳號或密碼錯誤", 401)
            else:
                conn.execute("DELETE FROM login_attempts WHERE username=?", (username,))
                conn.execute("DELETE FROM sessions WHERE expires_at<=?", (_iso(now),))
                token = secrets.token_urlsafe(32)
                expires = _iso(now + timedelta(hours=SESSION_HOURS))
                conn.execute("INSERT INTO sessions VALUES(?,?,?,?)",
                             (hashlib.sha256(token.encode()).hexdigest(), row["id"], expires, _iso(now)))
                self._audit(conn, row["id"], "session.login", "session")
                result = {"token": token, "expires_at": expires, "user": self._user(row)}
        if error:
            raise error
        return result

    def user_for_token(self, token):
        if not isinstance(token, str) or not token or len(token) > 256:
            raise DomainError("請先登入", 401)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
                               (hashlib.sha256(token.encode()).hexdigest(), _iso(_now()))).fetchone()
            if not row:
                raise DomainError("登入已逾期，請重新登入", 401)
            return self._user(row)

    def logout(self, token):
        if not isinstance(token, str):
            return {"ok": True}
        with self._transaction() as conn:
            digest = hashlib.sha256(token.encode()).hexdigest()
            row = conn.execute("SELECT user_id FROM sessions WHERE token_hash=?", (digest,)).fetchone()
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
            if row:
                self._audit(conn, row["user_id"], "session.logout", "session")
        return {"ok": True}

    @staticmethod
    def _manager(actor):
        if actor["role"] not in {"admin", "manager"}:
            raise DomainError("此操作需要主管權限", 403)

    @staticmethod
    def _scope(actor, query):
        value = query.get("user_id")
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None or value == "":
            return actor["id"] if actor["role"] == "employee" else None
        result = _int(value, "員工編號", 1)
        if actor["role"] == "employee" and result != actor["id"]:
            raise DomainError("員工只能讀取自己的資料", 403)
        return result

    @staticmethod
    def _month(query):
        value = query.get("month", _now().strftime("%Y-%m"))
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
            raise DomainError("月份須為 YYYY-MM")
        first = _date(value + "-01", "月份")
        return value, first, _add_months(first, 1)

    @staticmethod
    def _effective_punches(conn, user_id=None):
        sql = "SELECT p.*,u.username,u.name FROM punches p JOIN users u ON u.id=p.user_id WHERE NOT EXISTS(SELECT 1 FROM punches x WHERE x.supersedes=p.id)"
        params = []
        if user_id is not None:
            sql += " AND p.user_id=?"
            params.append(user_id)
        return [dict(row) for row in conn.execute(sql + " ORDER BY p.occurred_at,p.id", params)]

    @staticmethod
    def _state(events):
        state = "out"
        transitions = {("out", "in"): "in", ("in", "out"): "out", ("in", "break_start"): "break", ("break", "break_end"): "in"}
        for event in events:
            new_state = transitions.get((state, event["kind"]))
            if new_state is None:
                raise DomainError("打卡順序不成立：上班 → 休息開始／結束 → 下班；請先補齊缺漏紀錄", 409)
            state = new_state
        return state

    def _clock(self, conn, actor, data):
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            raise DomainError("打卡類型須為 in/out/break_start/break_end")
        if any(key in data for key in ("time", "occurred_at", "timestamp", "user_id")):
            raise DomainError("打卡使用伺服器臺灣時間及登入身分，不接受指定時間或員工")
        events = self._effective_punches(conn, actor["id"])
        now = _iso(_now())
        if events and events[-1]["occurred_at"] >= now:
            raise DomainError("最新打卡時間超過伺服器時間，請由主管檢查", 409)
        self._state(events + [{"kind": kind}])
        cursor = conn.execute("INSERT INTO punches(user_id,kind,occurred_at,source,created_at) VALUES(?,?,?,'clock',?)",
                              (actor["id"], kind, now, now))
        self._audit(conn, actor["id"], "punch.created", "punch", cursor.lastrowid, {"kind": kind, "occurred_at": now})
        return dict(conn.execute("SELECT * FROM punches WHERE id=?", (cursor.lastrowid,)).fetchone())

    def clock(self, user, kind):
        return self.handle(user, "POST", "/api/clock", {"kind": kind}, {})

    def punches(self, user, month):
        return self.handle(user, "GET", "/api/punches", {}, {"month": month})

    @staticmethod
    def _shift(schedule):
        start = datetime.combine(_date(schedule["date"]), time.fromisoformat(schedule["start"]), TZ)
        end = datetime.combine(_date(schedule["date"]), time.fromisoformat(schedule["end"]), TZ)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    def _schedule_write(self, conn, actor, data, schedule_id=None):
        self._manager(actor)
        user_id = _int(data.get("user_id"), "員工編號", 1)
        if not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (user_id,)).fetchone():
            raise DomainError("員工不存在或已停用", 404)
        on = _date(data.get("date"))
        start, end = data.get("start"), data.get("end")
        for value in (start, end):
            if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                raise DomainError("班次時間須為 HH:MM")
        if start == end:
            raise DomainError("班次起訖不可相同")
        break_minutes = _int(data.get("break_minutes", 0), "預定休息分鐘", 0, 720)
        day_type = data.get("day_type", "workday")
        if not isinstance(day_type, str) or day_type not in DAY_TYPES:
            raise DomainError("無效的工作日類別")
        values = {"user_id": user_id, "date": str(on), "start": start, "end": end,
                  "break_minutes": break_minutes, "day_type": day_type,
                  "holiday_name": _text(data.get("holiday_name", ""), "假日名稱", 120, False)}
        shift_start, shift_end = self._shift(values)
        shift_minutes = int((shift_end - shift_start).total_seconds() / 60)
        if break_minutes >= shift_minutes or shift_minutes - break_minutes > 720:
            raise DomainError("排班扣除休息後須大於 0 且不超過 12 小時；仍須另外確認法定工時與休息規定")
        if day_type == "workday" and shift_minutes - break_minutes > 480:
            raise DomainError("本系統採一般工時：工作日正常排班最多 8 小時，加班須另外申請")
        other = conn.execute("SELECT * FROM schedules WHERE user_id=? AND date BETWEEN ? AND ? AND id<>?",
                             (user_id, str(on - timedelta(days=1)), str(on + timedelta(days=1)), schedule_id or -1)).fetchall()
        for existing in other:
            a, b = self._shift(existing)
            if max(a, shift_start) < min(b, shift_end):
                raise DomainError("班次與既有排班重疊", 409)
        # Editing an already reserved leave window could invalidate its quota.
        affected = conn.execute("SELECT 1 FROM requests WHERE user_id=? AND kind='leave' AND status IN ('pending','approved') AND start_at<? AND end_at>? LIMIT 1",
                                (user_id, _iso(shift_end), _iso(shift_start))).fetchone()
        if affected:
            raise DomainError("此時段已有待簽核或核准請假，請先取消待簽核申請或由人資處理異動", 409)
        columns = (user_id, str(on), start, end, break_minutes, day_type, values["holiday_name"], actor["id"], _iso(_now()))
        try:
            if schedule_id:
                existing = conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
                if not existing:
                    raise DomainError("排班不存在", 404)
                old_start, old_end = self._shift(existing)
                if conn.execute("SELECT 1 FROM requests WHERE user_id=? AND kind='leave' AND status IN ('pending','approved') AND start_at<? AND end_at>?", (existing["user_id"], _iso(old_end), _iso(old_start))).fetchone():
                    raise DomainError("既有班次已被請假申請引用，不能直接更改", 409)
                conn.execute("UPDATE schedules SET user_id=?,date=?,start=?,end=?,break_minutes=?,day_type=?,holiday_name=?,created_by=?,updated_at=? WHERE id=?", columns + (schedule_id,))
            else:
                cursor = conn.execute("INSERT INTO schedules(user_id,date,start,end,break_minutes,day_type,holiday_name,created_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", columns)
                schedule_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise DomainError("此員工當日已有排班，請使用編輯功能", 409) from None
        self._audit(conn, actor["id"], "schedule.saved", "schedule", schedule_id, values)
        return dict(conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone())

    def _leave_capacity(self, conn, user_id, start, end):
        rows = conn.execute("SELECT * FROM schedules WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date",
                            (user_id, str(start.date() - timedelta(days=1)), str(end.date()))).fetchall()
        portions = []
        for row in rows:
            if row["day_type"] != "workday":
                continue
            a, b = self._shift(row)
            overlap = max(0, (min(b, end) - max(a, start)).total_seconds() / 60)
            if overlap:
                # Breaks have no clock position in this schema. A partial request
                # declares its real leave minutes; this is an upper bound only.
                capacity = min(overlap, (b - a).total_seconds() / 60 - row["break_minutes"])
                portions.append((row["date"], capacity))
        return portions

    def _validate_leave(self, conn, employee, data, exclude_id=None):
        from .labor import annual_leave_days, leave_policy

        kind = data["leave_type"]
        try:
            policy = leave_policy(kind)
        except (ValueError, KeyError):
            raise DomainError("不支援的假別") from None
        start, end = _timestamp(data["start_at"]), _timestamp(data["end_at"])
        minutes = data["requested_minutes"]
        if start.date() < _date(employee["hire_date"]):
            raise DomainError("請假不可早於到職日")
        portions = self._leave_capacity(conn, employee["id"], start, end)
        capacity = sum(item[1] for item in portions)
        if capacity <= 0:
            raise DomainError("請假時段沒有工作日排班，請先請主管建立排班；休息日與假日不可扣請假額度")
        if minutes > capacity:
            raise DomainError("申請分鐘超過排班重疊的可請假分鐘；請排除休息與非工作日")
        reserved = [dict(row) for row in conn.execute("SELECT * FROM requests WHERE user_id=? AND kind='leave' AND status IN ('pending','approved') AND id<>?",
                                                     (employee["id"], exclude_id or -1))]
        if any(max(start, _timestamp(row["start_at"])) < min(end, _timestamp(row["end_at"])) for row in reserved):
            raise DomainError("請假時段與既有待簽核或核准申請重疊", 409)
        # Non-overlapping requests can still exhaust one shift's net capacity:
        # e.g. 09-13 (240) plus 13-18 (300) in a 480-minute shift.
        allocated = {}
        for request in reserved + [data]:
            remaining = request["requested_minutes"]
            request_parts = self._leave_capacity(conn, employee["id"], _timestamp(request["start_at"]), _timestamp(request["end_at"]))
            for on, available in request_parts:
                part = min(remaining, available)
                allocated[on] = allocated.get(on, 0) + part
                remaining -= part
        for on, used_minutes in allocated.items():
            schedule = conn.execute("SELECT * FROM schedules WHERE user_id=? AND date=?", (employee["id"], on)).fetchone()
            a, b = self._shift(schedule)
            if used_minutes > (b-a).total_seconds()/60 - schedule["break_minutes"]:
                raise DomainError(f"{on} 多筆請假合計超過當日淨排班分鐘，請排除休息時段", 409)
        last_day = (end - timedelta(microseconds=1)).date()
        if kind == "annual":
            period_start, period_end = _annual_period(_date(employee["hire_date"]), start.date())
            if last_day >= period_end:
                raise DomainError("特休申請跨越到職週年額度邊界，請分開申請")
            quota = annual_leave_days(employee["hire_date"], str(start.date())) * 480
            used = sum(row["requested_minutes"] for row in reserved if row["leave_type"] == "annual" and period_start <= _timestamp(row["start_at"]).date() < period_end)
            if used + minutes > quota:
                raise DomainError(f"特休額度不足：本期 {quota} 分鐘，已核准或保留 {used} 分鐘（以每日 8 小時換算）", 409)
        elif kind in {"personal", "sick", "family_care", "family_care_personal", "menstrual"}:
            if start.year != last_day.year:
                raise DomainError("請假申請跨越曆年額度邊界，請分開申請")
            this_year = [row for row in reserved if _timestamp(row["start_at"]).year == start.year]
            def total(kinds):
                return sum(row["requested_minutes"] for row in this_year if row["leave_type"] in kinds)
            personal = {"personal", "family_care", "family_care_personal"}
            if kind in personal and total(personal) + minutes > 14 * 480:
                raise DomainError("事假與家庭照顧相關事假合計超過年度 14 日額度", 409)
            if kind == "family_care" and total({"family_care"}) + minutes > 7 * 480:
                raise DomainError("家庭照顧假超過年度 7 日額度", 409)
            if kind == "menstrual":
                if start.month != last_day.month:
                    raise DomainError("生理假跨越月份，請分開申請")
                monthly = sum(row["requested_minutes"] for row in this_year if row["leave_type"] == "menstrual" and _timestamp(row["start_at"]).month == start.month)
                if monthly + minutes > 480:
                    raise DomainError("生理假每月最多 1 日（本原型以 8 小時換算）", 409)
            sick = total({"sick"}) + (minutes if kind == "sick" else 0)
            menstrual = total({"menstrual"}) + (minutes if kind == "menstrual" else 0)
            if kind == "sick" and sick + max(0, menstrual - 3 * 480) > 30 * 480:
                raise DomainError("普通傷病假與須併計生理假超過非住院年度 30 日；住院等例外請由人資另行處理", 409)
        # Event-based entitlements need documentary and eligibility review.
        # Do not turn their per-event days into an annual cap.
        return {"policy": policy, "available_scheduled_minutes": capacity}

    def _request_create(self, conn, actor, data):
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in {"leave", "correction", "overtime"}:
            raise DomainError("申請類型須為 leave/correction/overtime")
        if "user_id" in data and _int(data["user_id"], "員工編號", 1) != actor["id"]:
            raise DomainError("只能替自己提出申請", 403)
        reason = _text(data.get("reason"), "申請原因", 2000)
        values = {"user_id": actor["id"], "kind": kind, "reason": reason, "requested_minutes": 0,
                  "start_at": None, "end_at": None, "leave_type": None, "correction_kind": None,
                  "correction_at": None, "target_punch_id": None, "created_at": _iso(_now())}
        if kind == "correction":
            punch_kind = data.get("correction_kind")
            if not isinstance(punch_kind, str) or punch_kind not in KINDS:
                raise DomainError("補卡類型須為 in/out/break_start/break_end")
            occurred = _timestamp(data.get("correction_at"), "補卡時間")
            if occurred > _now():
                raise DomainError("不可申請未來的補卡")
            if occurred.date() < _date(actor["hire_date"]):
                raise DomainError("補卡不可早於到職日")
            target = data.get("target_punch_id")
            if target not in (None, ""):
                target = _int(target, "被更正打卡編號", 1)
                if not conn.execute("SELECT 1 FROM punches WHERE id=? AND user_id=?", (target, actor["id"])).fetchone():
                    raise DomainError("被更正打卡不存在或不屬於本人", 404)
            values.update(correction_kind=punch_kind, correction_at=_iso(occurred), target_punch_id=target or None)
        else:
            start, end = _timestamp(data.get("start_at"), "開始時間"), _timestamp(data.get("end_at"), "結束時間")
            if end <= start or end - start > timedelta(days=180):
                raise DomainError("申請結束時間須晚於開始，單次跨度不得超過 180 日")
            minutes = _int(data.get("requested_minutes"), "實際申請分鐘", 1, 180 * 24 * 60)
            if minutes * 60 > (end - start).total_seconds():
                raise DomainError("申請分鐘不可超過起訖時間跨度")
            values.update(start_at=_iso(start), end_at=_iso(end), requested_minutes=minutes)
            if kind == "leave":
                values["leave_type"] = _text(data.get("leave_type"), "假別", 40)
                self._validate_leave(conn, actor, values)
            else:
                if end - start > timedelta(hours=24):
                    raise DomainError("加班申請須拆為每日申請，單次跨度不得超過 24 小時")
                if start.date() < _date(actor["hire_date"]):
                    raise DomainError("加班不可早於到職日")
                overlap = conn.execute("SELECT 1 FROM requests WHERE user_id=? AND kind='overtime' AND status IN ('pending','approved') AND start_at<? AND end_at>?", (actor["id"], _iso(end), _iso(start))).fetchone()
                if overlap:
                    raise DomainError("加班時段與既有申請重疊", 409)
        fields = list(values)
        cursor = conn.execute(f"INSERT INTO requests({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", tuple(values.values()))
        self._audit(conn, actor["id"], "request.created", "request", cursor.lastrowid, {"kind": kind})
        return dict(conn.execute("SELECT r.*,u.name,u.username FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=?", (cursor.lastrowid,)).fetchone())

    def _request_review(self, conn, actor, request_id, data, validate_correction=True):
        self._manager(actor)
        row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise DomainError("申請不存在", 404)
        if row["user_id"] == actor["id"]:
            raise DomainError("不可簽核自己的申請，須由另一位主管或管理員處理", 403)
        if row["status"] != "pending":
            raise DomainError("此申請已處理，不能重複簽核", 409)
        decision = data.get("decision")
        if not isinstance(decision, str) or decision not in {"approved", "rejected"}:
            raise DomainError("簽核決定須為 approved/rejected")
        comment = _text(data.get("comment", ""), "簽核意見", 2000, False)
        if decision == "approved" and row["kind"] == "leave":
            employee = conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
            validation = self._validate_leave(conn, employee, row, row["id"])
            if validation["policy"].get("period") in {"event", "event_calendar_days", "pregnancy_event", "actual_need"} and not comment:
                raise DomainError("此假別需人工核對事件、親屬關係、請休期間及剩餘額度；請在簽核意見記錄核對依據")
        if decision == "approved" and row["kind"] == "correction" and validate_correction:
            events = self._effective_punches(conn, row["user_id"])
            if row["target_punch_id"]:
                if not any(event["id"] == row["target_punch_id"] for event in events):
                    raise DomainError("原始打卡已被其他核准補卡更正", 409)
                events = [event for event in events if event["id"] != row["target_punch_id"]]
            if any(event["occurred_at"] == row["correction_at"] for event in events):
                raise DomainError("同一時間已有打卡紀錄", 409)
            events.append({"kind": row["correction_kind"], "occurred_at": row["correction_at"], "id": 2**63 - 1})
            events.sort(key=lambda event: (event["occurred_at"], event["id"]))
            self._state(events)
        if decision == "approved" and row["kind"] == "correction":
            conn.execute("INSERT INTO punches(user_id,kind,occurred_at,source,request_id,supersedes,created_at) VALUES(?,?,?,'correction',?,?,?)",
                         (row["user_id"], row["correction_kind"], row["correction_at"], row["id"], row["target_punch_id"], _iso(_now())))
        conn.execute("UPDATE requests SET status=?,reviewer_id=?,review_comment=?,reviewed_at=? WHERE id=? AND status='pending'",
                     (decision, actor["id"], comment, _iso(_now()), request_id))
        self._audit(conn, actor["id"], "request." + decision, "request", request_id, {"kind": row["kind"], "comment": comment})
        return dict(conn.execute("SELECT r.*,u.name,u.username FROM requests r JOIN users u ON u.id=r.user_id WHERE r.id=?", (request_id,)).fetchone())

    def _review_batch(self, conn, actor, data):
        self._manager(actor)
        request_ids = data.get("request_ids")
        if not isinstance(request_ids, list) or not 1 <= len(request_ids) <= 100:
            raise DomainError("request_ids 須為包含 1–100 筆補卡申請編號的陣列")
        ids = [_int(value, "申請編號", 1) for value in request_ids]
        if len(set(ids)) != len(ids):
            raise DomainError("批次申請編號不可重複")
        rows = [conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone() for request_id in ids]
        if any(not row for row in rows):
            raise DomainError("批次包含不存在的申請", 404)
        if len({row["user_id"] for row in rows}) != 1 or any(row["kind"] != "correction" for row in rows):
            raise DomainError("批次簽核限同一員工的補卡申請")
        if rows[0]["user_id"] == actor["id"]:
            raise DomainError("不可簽核自己的申請", 403)
        if any(row["status"] != "pending" for row in rows):
            raise DomainError("批次包含已處理的申請", 409)
        if data.get("decision") == "approved":
            events = self._effective_punches(conn, rows[0]["user_id"])
            targets = [row["target_punch_id"] for row in rows if row["target_punch_id"]]
            if len(set(targets)) != len(targets):
                raise DomainError("同一批不可重複更正同一筆打卡", 409)
            if any(not any(event["id"] == target for event in events) for target in targets):
                raise DomainError("批次包含已被更正的原始打卡", 409)
            events = [event for event in events if event["id"] not in targets]
            events.extend({"kind": row["correction_kind"], "occurred_at": row["correction_at"], "id": 2**62 + row["id"]} for row in rows)
            times = [event["occurred_at"] for event in events]
            if len(times) != len(set(times)):
                raise DomainError("批次補卡產生相同時間的重複紀錄", 409)
            events.sort(key=lambda event: (event["occurred_at"], event["id"]))
            self._state(events)
        return {"requests": [self._request_review(conn, actor, request_id, data, validate_correction=False) for request_id in ids]}

    def _report(self, conn, actor, query):
        month, first, end = self._month(query)
        scope = self._scope(actor, query)
        users = [self._user(row) for row in conn.execute("SELECT * FROM users" + (" WHERE id=?" if scope else ""), (scope,) if scope else ())]
        output = []
        for employee in users:
            user_id = employee["id"]
            daily = {}
            def get_day(on):
                if on not in daily:
                    daily[on] = {"user_id": user_id, "name": employee["name"], "date": on,
                                 "first_in": None, "last_out": None, "work_minutes": 0,
                                 "break_minutes": 0, "status": "no_punch", "day_type": None,
                                 "scheduled_minutes": 0, "leave_minutes": 0,
                                 "approved_overtime_minutes": 0, "issues": []}
                return daily[on]
            for schedule in conn.execute("SELECT * FROM schedules WHERE user_id=? AND date>=? AND date<?", (user_id, str(first), str(end))):
                day = get_day(schedule["date"])
                a, b = self._shift(schedule)
                day.update(day_type=schedule["day_type"], scheduled_minutes=(b-a).total_seconds()/60-schedule["break_minutes"])
            # A night shift belongs to its clock-in date, including its after-midnight part.
            current = None
            for punch in self._effective_punches(conn, user_id):
                moment = _timestamp(punch["occurred_at"])
                if punch["kind"] == "in":
                    current = {"start": moment, "break_start": None, "break_seconds": 0, "long_work": False,
                               "segment_start": moment, "continuous_work_seconds": 0}
                elif current and punch["kind"] == "break_start":
                    current["continuous_work_seconds"] += (moment-current["segment_start"]).total_seconds()
                    current["long_work"] |= current["continuous_work_seconds"] > 4*3600
                    current["break_start"] = moment
                elif current and punch["kind"] == "break_end":
                    duration = (moment-current["break_start"]).total_seconds()
                    current["break_seconds"] += duration
                    if duration >= 30*60:
                        current["continuous_work_seconds"] = 0
                    current["break_start"] = None
                    current["segment_start"] = moment
                elif current and punch["kind"] == "out":
                    on = str(current["start"].date())
                    if str(first) <= on < str(end):
                        day = get_day(on)
                        day["first_in"] = day["first_in"] or _iso(current["start"])
                        day["last_out"] = _iso(moment)
                        span = (moment-current["start"]).total_seconds()
                        current["continuous_work_seconds"] += (moment-current["segment_start"]).total_seconds()
                        current["long_work"] |= current["continuous_work_seconds"] > 4*3600
                        if span > 24*3600:
                            day["work_minutes"] = None
                            day["issues"].append("單次出勤超過 24 小時，疑似漏卡，未列計工時")
                        elif day["work_minutes"] is not None:
                            day["work_minutes"] += (span-current["break_seconds"])/60
                        day["break_minutes"] += current["break_seconds"]/60
                        if current["long_work"]:
                            day["issues"].append("存在未經至少 30 分鐘休息、累計出勤超過 4 小時區段，須確認法定休息或例外")
                        day["status"] = "review_required" if day["issues"] else "complete"
                    current = None
            if current and first <= current["start"].date() < end:
                day = get_day(str(current["start"].date()))
                day["first_in"] = day["first_in"] or _iso(current["start"])
                day["work_minutes"] = None
                day["status"] = "incomplete"
                day["issues"].append("尚無完整下班紀錄，未推估工時")
            approved = conn.execute("SELECT * FROM requests WHERE user_id=? AND status='approved' AND kind IN ('leave','overtime')", (user_id,)).fetchall()
            for request in approved:
                a, b = _timestamp(request["start_at"]), _timestamp(request["end_at"])
                if request["kind"] == "overtime":
                    on = str(a.date())
                    if str(first) <= on < str(end):
                        get_day(on)["approved_overtime_minutes"] += request["requested_minutes"]
                else:
                    portions = self._leave_capacity(conn, user_id, a, b)
                    remaining = request["requested_minutes"]
                    # Declared net minutes are allocated chronologically, not inferred from elapsed days.
                    for on, capacity in portions:
                        part = min(remaining, capacity)
                        if str(first) <= on < str(end):
                            get_day(on)["leave_minutes"] += part
                        remaining -= part
            output.extend(daily[on] for on in sorted(daily))
        return {"month": month, "timezone": "Asia/Taipei", "rows": sorted(output, key=lambda row: (row["date"], row["user_id"])),
                "notes": ["工時僅由上班、下班及實際休息打卡計算；預定休息不自動扣除。",
                          "跨午夜班次歸屬上班日。未完成或超過 24 小時的班次不推估工時。",
                          "加班核准分鐘不等於已實際出勤或最終薪資；多日請假淨分鐘依排班順序分配，請逐日申請以保留每日精確分布。"]}

    def handle(self, user: dict, method: str, path: str, data: dict | None = None, query: dict | None = None):
        data, query = data or {}, query or {}
        method = method.upper()
        if not isinstance(data, dict) or not isinstance(query, dict):
            raise DomainError("請求資料須為 JSON 物件")
        with self._transaction() as conn:
            actor_row = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (user.get("id"),)).fetchone()
            if not actor_row:
                raise DomainError("請先登入", 401)
            actor = self._user(actor_row)
            if path == "/api/users":
                if method == "GET":
                    if actor["role"] == "employee":
                        return [actor]
                    return [self._user(row) for row in conn.execute("SELECT * FROM users ORDER BY id")]
                if method == "POST":
                    self._manager(actor)
                    return self._create_user(conn, data, actor)
            if path == "/api/password" and method == "POST":
                if not _verify(data.get("current_password"), actor_row["password_salt"], actor_row["password_hash"]):
                    raise DomainError("目前密碼錯誤", 403)
                salt, digest = _password(data.get("new_password"))
                conn.execute("UPDATE users SET password_salt=?,password_hash=? WHERE id=?", (salt, digest, actor["id"]))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (actor["id"],))
                self._audit(conn, actor["id"], "user.password_changed", "user", actor["id"])
                return {"ok": True, "reauthenticate": True}
            if path == "/api/clock" and method == "POST":
                return self._clock(conn, actor, data)
            if path == "/api/punches" and method == "GET":
                _, first, end = self._month(query)
                scope = self._scope(actor, query)
                return [row for row in self._effective_punches(conn, scope) if str(first) <= row["occurred_at"][:10] < str(end)]
            if path == "/api/schedules":
                if method == "GET":
                    _, first, end = self._month(query)
                    scope = self._scope(actor, query)
                    sql = "SELECT s.*,u.name,u.username FROM schedules s JOIN users u ON u.id=s.user_id WHERE s.date>=? AND s.date<?"
                    args = [str(first), str(end)]
                    if scope:
                        sql += " AND s.user_id=?"
                        args.append(scope)
                    return [dict(row) for row in conn.execute(sql + " ORDER BY s.date,s.user_id", args)]
                if method == "POST":
                    return self._schedule_write(conn, actor, data)
            match = re.fullmatch(r"/api/schedules/(\d+)", path)
            if match and method in {"PUT", "PATCH", "DELETE"}:
                self._manager(actor)
                schedule_id = _int(match[1], "排班編號", 1)
                if method != "DELETE":
                    return self._schedule_write(conn, actor, data, schedule_id)
                row = conn.execute("SELECT * FROM schedules WHERE id=?", (schedule_id,)).fetchone()
                if not row:
                    raise DomainError("排班不存在", 404)
                a, b = self._shift(row)
                if conn.execute("SELECT 1 FROM requests WHERE user_id=? AND kind='leave' AND status IN ('pending','approved') AND start_at<? AND end_at>?", (row["user_id"], _iso(b), _iso(a))).fetchone():
                    raise DomainError("排班已有待簽核或核准請假，不能刪除", 409)
                conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
                self._audit(conn, actor["id"], "schedule.deleted", "schedule", schedule_id, dict(row))
                return {"ok": True}
            if path == "/api/requests":
                if method == "GET":
                    scope = self._scope(actor, query)
                    sql = "SELECT r.*,u.name,u.username FROM requests r JOIN users u ON u.id=r.user_id"
                    args = []
                    if scope:
                        sql += " WHERE r.user_id=?"
                        args.append(scope)
                    return [dict(row) for row in conn.execute(sql + " ORDER BY r.id DESC", args)]
                if method == "POST":
                    return self._request_create(conn, actor, data)
            if path == "/api/requests/review-batch" and method == "POST":
                return self._review_batch(conn, actor, data)
            match = re.fullmatch(r"/api/requests/(\d+)/review", path)
            if match and method == "POST":
                return self._request_review(conn, actor, _int(match[1], "申請編號", 1), data)
            match = re.fullmatch(r"/api/requests/(\d+)", path)
            if match and method == "DELETE":
                row = conn.execute("SELECT * FROM requests WHERE id=?", (_int(match[1], "申請編號", 1),)).fetchone()
                if not row or row["user_id"] != actor["id"]:
                    raise DomainError("申請不存在或不屬於本人", 404)
                if row["status"] != "pending":
                    raise DomainError("只能取消尚未簽核的申請", 409)
                conn.execute("UPDATE requests SET status='cancelled' WHERE id=?", (row["id"],))
                self._audit(conn, actor["id"], "request.cancelled", "request", row["id"])
                return {"ok": True}
            if path == "/api/report" and method == "GET":
                return self._report(conn, actor, query)
            if path == "/api/audit" and method == "GET":
                self._manager(actor)
                rows = conn.execute("SELECT a.*,u.name AS actor_name FROM audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 1000")
                return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows]
            raise DomainError("找不到此 API 或不支援此方法", 404)
