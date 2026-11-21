"""显式创建管理员或修改密码：python -m app.manage_auth <命令> <用户名>。"""

import argparse
import getpass
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.services.auth import get_auth_service


def main() -> int:
    """交互式隐藏密码；自动化可用标准输入，避免密码进入命令行及进程列表。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create-admin", "set-password"))
    parser.add_argument("username")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("密码：")
        if password != getpass.getpass("再次输入密码："):
            parser.error("两次输入的密码不一致")
    try:
        service = get_auth_service()
        if args.command == "create-admin":
            service.create_admin(args.username, password)
        else:
            service.set_password(args.username, password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("账号数据库操作失败，请检查配置并执行数据库迁移。", file=sys.stderr)
        return 1
    print(f"账号 {args.username}：{'已创建' if args.command == 'create-admin' else '密码已更新，旧会话已撤销'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
