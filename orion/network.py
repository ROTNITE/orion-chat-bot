"""Telegram HTTP session construction shared by the bot and diagnostics."""
from __future__ import annotations

import socket

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from .config import Config


class OrionAiohttpSession(AiohttpSession):
    """AiohttpSession with an optional IPv4-only direct-connection fallback.

    aiogram 3.31 stores TCPConnector kwargs in ``_connector_init``.  We only
    add ``family=AF_INET`` for direct connections. Proxy connectors are left
    untouched because SOCKS/HTTP proxy resolution has its own rules.
    """

    def __init__(self, *, proxy: str | None, force_ipv4: bool, timeout: float) -> None:
        super().__init__(proxy=proxy, timeout=timeout)
        if force_ipv4 and proxy is None:
            self._connector_init["family"] = socket.AF_INET


def create_bot(config: Config) -> Bot:
    session = OrionAiohttpSession(
        proxy=config.telegram_proxy,
        force_ipv4=config.force_ipv4,
        timeout=config.telegram_timeout,
    )
    return Bot(token=config.token, session=session)
