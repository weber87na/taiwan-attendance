"""Run from the project root: python -m attendance init / serve / backup."""
import argparse
from contextlib import closing
import getpass
import logging
import os
from pathlib import Path
import sqlite3

from .store import DomainError, Store


def main():
    parser = argparse.ArgumentParser(description="台灣出勤管理")
    parser.add_argument("--db", default="runtime/attendance.sqlite3", help="SQLite 資料庫位置")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="互動建立第一位管理員")
    init.add_argument("--username", default="admin")
    init.add_argument("--name", default="管理員")
    serve = commands.add_parser("serve", help="啟動本機介面")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--public-origin", help="反向代理的 origin，例如 https://attendance.example.com")
    serve.add_argument("--secure-cookie", action="store_true", help="僅透過 HTTPS 傳送 session cookie")
    backup = commands.add_parser("backup", help="SQLite 一致性備份（含個人資料）")
    backup.add_argument("destination", help="新的備份檔案位置，禁止覆蓋")
    args = parser.parse_args()
    if hasattr(os, "umask"):
        os.umask(0o077)
    db = Path(args.db).resolve()
    if args.command == "backup":
        if not db.is_file():
            parser.error("資料庫不存在")
        destination = Path(args.destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb"):
                pass
        except FileExistsError:
            parser.error("目的檔案已存在，請使用新的檔名")
        try:
            with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(destination)) as target:
                source.backup(target)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        print(f"備份完成：{destination}")
        return
    db.parent.mkdir(parents=True, exist_ok=True)
    store = Store(str(db))
    if args.command == "init":
        password = getpass.getpass("管理員密碼（至少 12 字元）：")
        if password != getpass.getpass("再輸入一次："):
            parser.error("兩次密碼不一致")
        try:
            user = store.bootstrap(args.username, password, args.name)
        except DomainError as error:
            parser.error(str(error))
        print(f"已建立管理員：{user['username']}")
    else:
        from .server import AttendanceServer
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        try:
            server = AttendanceServer((args.host, args.port), store, public_origin=args.public_origin, secure_cookie=args.secure_cookie)
        except ValueError as error:
            parser.error(str(error))
        print(f"台灣出勤：http://{args.host}:{server.server_port} （Ctrl+C 停止）", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
