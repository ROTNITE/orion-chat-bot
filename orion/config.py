"""Runtime configuration; never print or log the bot token."""
from dataclasses import dataclass
import os
from dotenv import load_dotenv


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class Config:
    token: str
    db_path: str
    owner_id: int
    log_level: str
    telegram_proxy: str | None
    force_ipv4: bool
    telegram_timeout: float


def get_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token or token == "replace-with-botfather-token" or ":" not in token:
        raise SystemExit(
            "BOT_TOKEN missing/invalid. Run START_ORION.cmd or set the token from @BotFather in .env."
        )
    proxy = os.getenv("TELEGRAM_PROXY", "").strip() or None
    try:
        timeout = float(os.getenv("TELEGRAM_TIMEOUT", "60"))
    except ValueError as exc:
        raise SystemExit("TELEGRAM_TIMEOUT must be a number of seconds.") from exc
    if timeout < 5:
        raise SystemExit("TELEGRAM_TIMEOUT must be at least 5 seconds.")
    return Config(
        token=token,
        db_path=os.getenv("DB_PATH", "./data/orion.sqlite3"),
        owner_id=int(os.getenv("OWNER_ID", "0")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        telegram_proxy=proxy,
        force_ipv4=_bool_env("FORCE_IPV4"),
        telegram_timeout=timeout,
    )
