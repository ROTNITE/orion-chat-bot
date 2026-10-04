"""Small live Telegram connectivity check used by the Windows launcher."""
from __future__ import annotations

import asyncio
import json
import sys

from aiogram.exceptions import TelegramAPIError, TelegramNetworkError

from .config import get_config
from .network import create_bot


async def _check() -> int:
    config = get_config()
    bot = create_bot(config)
    try:
        me = await bot.get_me(request_timeout=min(config.telegram_timeout, 15.0))
        print(json.dumps({
            "ok": True,
            "id": me.id,
            "username": me.username or "",
            "proxy": bool(config.telegram_proxy),
            "force_ipv4": config.force_ipv4,
        }, ensure_ascii=False))
        return 0
    except TelegramNetworkError as exc:
        print(json.dumps({
            "ok": False,
            "kind": "network",
            "error": str(exc)[:500],
        }, ensure_ascii=False))
        return 2
    except TelegramAPIError as exc:
        print(json.dumps({
            "ok": False,
            "kind": "telegram_api",
            "error": str(exc)[:500],
        }, ensure_ascii=False))
        return 3
    except Exception as exc:  # launcher should never dump a token-bearing traceback
        print(json.dumps({
            "ok": False,
            "kind": "unexpected",
            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
        }, ensure_ascii=False))
        return 4
    finally:
        await bot.session.close()


def main() -> None:
    try:
        code = asyncio.run(_check())
    except SystemExit as exc:
        print(json.dumps({"ok": False, "kind": "config", "error": str(exc)}, ensure_ascii=False))
        code = 5
    raise SystemExit(code)


if __name__ == "__main__":
    main()
