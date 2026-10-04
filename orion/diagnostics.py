"""Live Telegram connectivity check used by the Windows launcher."""
from __future__ import annotations

import argparse
import asyncio
import json

from aiogram.exceptions import TelegramAPIError, TelegramNetworkError

from .config import get_config
from .network import create_bot


async def _check(attempts: int, per_attempt_timeout: float) -> int:
    config = get_config()
    bot = create_bot(config)
    last_network_error = ""
    try:
        for attempt in range(1, attempts + 1):
            try:
                me = await bot.get_me(
                    request_timeout=min(config.telegram_timeout, per_attempt_timeout)
                )
                print(json.dumps({
                    "ok": True,
                    "id": me.id,
                    "username": me.username or "",
                    "proxy": bool(config.telegram_proxy),
                    "force_ipv4": config.force_ipv4,
                    "attempt": attempt,
                }, ensure_ascii=False))
                return 0
            except TelegramNetworkError as exc:
                last_network_error = str(exc)[:500]
                if attempt < attempts:
                    await asyncio.sleep(min(attempt, 2))
            except TelegramAPIError as exc:
                print(json.dumps({
                    "ok": False,
                    "kind": "telegram_api",
                    "error": str(exc)[:500],
                }, ensure_ascii=False))
                return 3

        print(json.dumps({
            "ok": False,
            "kind": "network",
            "error": last_network_error or "Telegram did not answer",
            "attempts": attempts,
            "proxy": bool(config.telegram_proxy),
            "force_ipv4": config.force_ipv4,
        }, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "kind": "unexpected",
            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
        }, ensure_ascii=False))
        return 4
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=8.0)
    args, _ = parser.parse_known_args()
    attempts = max(1, min(args.attempts, 5))
    timeout = max(3.0, min(args.timeout, 30.0))
    try:
        code = asyncio.run(_check(attempts, timeout))
    except SystemExit as exc:
        print(json.dumps({"ok": False, "kind": "config", "error": str(exc)}, ensure_ascii=False))
        code = 5
    raise SystemExit(code)


if __name__ == "__main__":
    main()
