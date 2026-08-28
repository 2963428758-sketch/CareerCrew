"""创建生产环境管理员账号 CLI 脚本。

用于容器部署或生产初次上线后初始化管理员账号（避免生产环境下 /api/auth/bootstrap 的 403 限制）。

用法：
    # 交互式输入密码：
    python -m scripts.create_admin --username admin

    # 命令行指定密码：
    python -m scripts.create_admin --username admin --password "MySecretPass123"

    # 在 Docker 容器内执行：
    docker compose exec app python -m scripts.create_admin --username admin --password "MySecretPass123"
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from argon2 import PasswordHasher  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from careercrew_api.auth.service import validate_password_policy  # noqa: E402
from careercrew_api.auth.store import PostgresAccountStore  # noqa: E402
from careercrew_core.state.settings import load_auth_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="CareerCrew 生产环境创建管理员账号")
    parser.add_argument("--username", "-u", required=True, help="管理员用户名")
    parser.add_argument("--password", "-p", help="管理员密码（若未提供则安全交互式输入）")
    parser.add_argument("--database-url", "-d", help="数据库 DSN（默认读取 settings/环境变量）")
    args = parser.parse_args()

    load_dotenv(override=True)

    username = args.username.strip()
    if not username:
        print("❌ 错误：用户名不能为空", file=sys.stderr)
        sys.exit(1)

    password = args.password
    if not password:
        password = getpass.getpass("请输入管理员密码（需8-64位，含字母和数字）: ")
        confirm = getpass.getpass("请再次输入管理员密码确认: ")
        if password != confirm:
            print("❌ 错误：两次输入的密码不一致", file=sys.stderr)
            sys.exit(1)

    try:
        validate_password_policy(password)
    except Exception as e:
        print(f"❌ 密码不符合安全策略: {e}", file=sys.stderr)
        sys.exit(1)

    dsn = args.database_url or os.environ.get("AUTH_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        try:
            auth_settings = load_auth_settings()
            dsn = auth_settings.database_url
        except Exception:
            pass

    if not dsn:
        print("❌ 错误：未找到数据库连接串（请提供 --database-url 或配置 DATABASE_URL 环境变量）", file=sys.stderr)
        sys.exit(1)

    store = PostgresAccountStore(dsn)
    hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32)
    pw_hash = hasher.hash(password)

    try:
        if not store.has_accounts():
            account = store.create_first_admin(username, pw_hash)
            print("✅ 成功初始化首个管理员账号！")
            print(f"   用户 ID: {account.get('id')}")
            print(f"   用户名: {account.get('username')}")
            print(f"   角色: {account.get('role')}")
        else:
            existing = store.account_by_username(username)
            if existing:
                print(f"⚠️ 用户名 '{username}' 已存在（ID: {existing.get('id')}，角色: {existing.get('role')}）", file=sys.stderr)
                sys.exit(1)
            account = store.create_account(username, pw_hash, role="admin", must_change=False)
            print("✅ 成功创建管理员账号！")
            print(f"   用户 ID: {account.get('id')}")
            print(f"   用户名: {account.get('username')}")
            print(f"   角色: {account.get('role')}")
    except Exception as e:
        print(f"❌ 数据库操作失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
