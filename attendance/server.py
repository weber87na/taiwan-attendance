"""Same-origin HTTP adapter. Defaults to a local, single-company application."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import secrets
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .store import DomainError, Store
from .calendar_tw import calendar_month
from .insurance import estimate_insurance
from .labor import annual_leave_days, leave_policy, leave_types, overtime_pay, validate_hours

WEB = Path(__file__).resolve().parent.parent / "web"
COOKIE_NAME = "attendance_session"
MAX_BODY = 65536


def csv_export(rows: list[dict]) -> str:
    """Protect exported employee-controlled strings from spreadsheet formulas."""
    stream = io.StringIO(newline="")
    keys = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(stream, fieldnames=keys)
    writer.writeheader()
    for row in rows:
        safe = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                value = "'" + value
            safe[key] = value
        writer.writerow(safe)
    return "\ufeff" + stream.getvalue()


class AttendanceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: Store, *, public_origin=None, secure_cookie=False):
        self.store = store
        self.csrf_key = secrets.token_bytes(32)
        self.secure_cookie = secure_cookie
        super().__init__(address, Handler)
        host, port = self.server_address[:2]
        self.origins = {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}
        if host not in ("0.0.0.0", "::"):
            self.origins.add(f"http://{host}:{port}")
        if public_origin:
            parsed = urlsplit(public_origin)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
                self.server_close()
                raise ValueError("public-origin 必須是完整 http(s) origin，不含路徑")
            self.origins.add(f"{parsed.scheme}://{parsed.netloc}")
            if parsed.scheme == "https":
                self.secure_cookie = True
        self.hosts = {urlsplit(origin).netloc for origin in self.origins}

    def csrf(self, token):
        return hmac.new(self.csrf_key, token.encode(), hashlib.sha256).hexdigest()


class Handler(BaseHTTPRequestHandler):
    server_version = "TaiwanAttendance"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        # Never log passwords, request bodies, session cookies or query strings.
        logging.info("%s %s", self.command, urlsplit(self.path).path)

    def send_body(self, status, body, content_type="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""
        except Exception:
            return ""

    def cookie(self, token, expire=False):
        value = f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict"
        if expire:
            value += "; Max-Age=0"
        if self.server.secure_cookie:
            value += "; Secure"
        return value

    def json_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise DomainError("不支援此傳輸方式", 400)
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            raise DomainError("請使用 application/json", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise DomainError("Content-Length 格式錯誤", 400)
        if not 0 < length <= MAX_BODY:
            raise DomainError("JSON 內容為空或超過 64 KiB", 413)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeDecodeError):
            raise DomainError("JSON 格式錯誤", 400)
        if not isinstance(data, dict):
            raise DomainError("JSON 必須為物件", 400)
        return data

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_body(405, {"error": "僅提供同來源存取"})

    def dispatch(self, method):
        try:
            self.route(method)
        except DomainError as error:
            self.send_body(error.status, {"error": str(error)})
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            self.send_body(400, {"error": str(error) or "輸入資料有誤"})
        except Exception:
            logging.exception("Request failed")
            self.send_body(500, {"error": "伺服器處理失敗，請檢查主機記錄"})

    def route(self, method):
        if self.headers.get("Host", "") not in self.server.hosts:
            raise DomainError("Host 不在允許清單", 403)
        origin = self.headers.get("Origin")
        if origin and origin not in self.server.origins:
            raise DomainError("不允許跨來源請求", 403)
        parsed = urlsplit(self.path)
        path = parsed.path
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        if method == "GET" and path in ("/", "/index.html", "/app.js", "/style.css"):
            filename = "index.html" if path == "/" else path[1:]
            content_type = {"html": "text/html", "js": "text/javascript", "css": "text/css"}[filename.rsplit(".", 1)[1]]
            self.send_body(200, (WEB / filename).read_bytes(), content_type + "; charset=utf-8")
            return
        if method == "GET" and path == "/api/health":
            self.send_body(200, {"status": "ok", "version": __version__})
            return
        write = method in {"POST", "PUT", "PATCH", "DELETE"}
        empty_delete = method == "DELETE" and self.headers.get("Content-Length", "0") == "0" and not self.headers.get("Transfer-Encoding")
        data = self.json_body() if write and not empty_delete else {}
        if method == "POST" and path == "/api/login":
            result = self.server.store.login(data.get("username", ""), data.get("password", ""))
            token = result.pop("token")
            result["csrf_token"] = self.server.csrf(token)
            self.send_body(200, result, extra={"Set-Cookie": self.cookie(token)})
            return
        token = self.token()
        user = self.server.store.user_for_token(token)
        if write and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), self.server.csrf(token)):
            raise DomainError("安全驗證過期，請重新整理頁面", 403)
        if path == "/api/me" and method == "GET":
            self.send_body(200, {"user": user, "csrf_token": self.server.csrf(token)})
        elif path == "/api/logout" and method == "POST":
            self.server.store.logout(token)
            self.send_body(200, {"ok": True}, extra={"Set-Cookie": self.cookie("", expire=True)})
        elif path == "/api/calendar" and method == "GET":
            self.send_body(200, calendar_month(int(query["year"]), int(query["month"])))
        elif path == "/api/policies" and method == "GET":
            kinds = leave_types()
            self.send_body(200, {"verified_at": "2026-09-16", "timezone": "Asia/Taipei", "leave_types": {kind: leave_policy(kind) for kind in kinds}, "scope": "一般本國全時受僱者、正常工時制；金額為試算"})
        elif path == "/api/calculate/overtime" and method == "POST":
            self.send_body(200, overtime_pay(data["hourly_wage"], data["minutes"], data["day_type"]))
        elif path == "/api/calculate/insurance" and method == "POST":
            allowed = {"monthly_salary", "dependents", "occupational_rate", "pension_rate", "as_of"}
            if set(data) - allowed:
                raise DomainError("保費試算含未知欄位")
            self.send_body(200, estimate_insurance(**data))
        elif path == "/api/calculate/annual-leave" and method == "POST":
            self.send_body(200, {"days": annual_leave_days(data["hire_date"], data["as_of"])})
        elif path == "/api/calculate/hours" and method == "POST":
            self.send_body(200, {"warnings": validate_hours(data["daily_minutes"], data["weekly_minutes"], data["monthly_overtime_minutes"])})
        elif path == "/api/report.csv" and method == "GET":
            report = self.server.store.handle(user, "GET", "/api/report", {}, query)
            self.send_body(200, csv_export(report["rows"]), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="attendance.csv"'})
        else:
            result = self.server.store.handle(user, method, path, data, query)
            self.send_body(200, result)
