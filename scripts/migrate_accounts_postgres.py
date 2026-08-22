"""SQLite → Postgres 账号迁移（幂等；refresh 会话与登录限速/审计不迁移）。

默认 dry-run；--apply 才写 Postgres。--archive-sqlite 在 apply 成功后把
SQLite 文件改名为 <原名>.pre-postgres-<时间戳>.bak（默认启用于 apply）。
迁移完成后所有旧 refresh token 失效（未迁移会话），全员需重新登录。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SQLITE = PROJECT_ROOT / "data" / "db" / "accounts.db"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def sqlite_accounts(path: str | Path) -> list[dict]:
    db = Path(path)
    if not db.is_file():
        raise FileNotFoundError(f"sqlite accounts db not found: {db}")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
        select = "SELECT id, username, password_hash, role"
        select += ", status" if "status" in cols else ", 'active' AS status"
        select += ", token_version" if "token_version" in cols else ", 0 AS token_version"
        select += " FROM accounts ORDER BY created_at, id"
        rows = conn.execute(select).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"], "username": r["username"], "password_hash": r["password_hash"],
            "role": r["role"], "status": r["status"], "token_version": int(r["token_version"]),
        }
        for r in rows
    ]


def build_plan(sqlite_rows: list[dict], pg_rows: list[dict]) -> tuple[list[dict], list[tuple]]:
    """返回 (to_insert, conflicts)。同 id 且 username/role/password_hash 全等 → skip；
    任一不同 → conflict（不覆盖）。"""
    existing = {r["id"]: r for r in pg_rows}
    to_insert: list[dict] = []
    conflicts: list[tuple] = []
    for row in sqlite_rows:
        target = existing.get(row["id"])
        if target is None:
            to_insert.append(row)
            continue
        for field in ("username", "role", "password_hash"):
            if target.get(field) != row.get(field):
                conflicts.append((row["id"], field))
                break
    return to_insert, conflicts


def apply_migration(dsn: str, rows: list[dict]) -> int:
    import psycopg

    inserted = 0
    with psycopg.connect(dsn) as conn:
        for row in rows:
            with conn.transaction():
                conn.execute(
                    "INSERT INTO auth_accounts (id, username, password_hash, role, status, token_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    (row["id"], row["username"], row["password_hash"], row["role"],
                     row["status"], row["token_version"]),
                )
            inserted += 1
    return inserted


def _pg_accounts(dsn: str) -> list[dict]:
    import psycopg
    import psycopg.rows

    with psycopg.connect(dsn, row_factory=psycopg.rows.dict_row) as conn:
        rows = conn.execute(
            "SELECT id, username, password_hash, role, status, token_version FROM auth_accounts"
        ).fetchall()
    return [dict(r) for r in rows]


def _auth_dsn() -> str:
    sys.path.insert(0, str(PROJECT_ROOT))
    from careercrew_core.state.settings import load_auth_settings

    settings = load_auth_settings()
    if not settings.database_url:
        raise SystemExit("认证 DSN 缺失；先检查 AUTH_DATABASE_URL / DATABASE_URL")
    return settings.database_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-db", default=str(_DEFAULT_SQLITE))
    parser.add_argument("--postgres-dsn", default="", help="默认读 settings 的 auth.database_url")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive-sqlite", action="store_true", default=True)
    parser.add_argument("--no-archive-sqlite", action="store_false", dest="archive_sqlite")
    args = parser.parse_args(argv)

    dsn = args.postgres_dsn or _auth_dsn()
    try:
        rows = sqlite_accounts(args.sqlite_db)
    except FileNotFoundError:
        print(f"SQLite 账号库不存在（已归档或已迁移），无需迁移: {args.sqlite_db}")
        return 0
    if not rows:
        print("SQLite 账号表为空，无需迁移")
        return 0
    to_insert, conflicts = build_plan(rows, _pg_accounts(dsn))
    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} accounts={len(rows)} "
          f"to_insert={len(to_insert)} conflicts={len(conflicts)}")
    for source_id, field in conflicts:
        print(f"- CONFLICT account {source_id}: {field} differs")
    for row in to_insert:
        print(f"- {'APPLY' if args.apply else 'DRY-RUN'} insert {row['id']} ({row['username']}, {row['role']})")
    if args.apply and to_insert:
        apply_migration(dsn, to_insert)
        print(f"inserted={len(to_insert)}")
    if args.apply and args.archive_sqlite and to_insert:
        db = Path(args.sqlite_db)
        stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
        backup = db.with_name(f"{db.name}.pre-postgres-{stamp}.bak")
        db.rename(backup)
        print(f"ARCHIVE sqlite -> {backup}")
        print("注意：旧刷新令牌未迁移，全部用户需要重新登录。")
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
