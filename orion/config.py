"""Runtime configuration; never print or log the bot token."""
from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "да", "д"}


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
    # The launcher edits .env while it is running.  Explicit path + override=True
    # guarantees that every newly spawned Python process sees the values the user
    # just selected, even if Windows/PowerShell already has variables with the
    # same names in its inherited environment.
    load_dotenv(dotenv_path=ENV_PATH, override=True)

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

    db_raw = os.getenv("DB_PATH", "./data/orion.sqlite3").strip() or "./data/orion.sqlite3"
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    try:
        owner_id = int(os.getenv("OWNER_ID", "0"))
    except ValueError as exc:
        raise SystemExit("OWNER_ID must be an integer Telegram user ID.") from exc

    return Config(
        token=token,
        db_path=str(db_path),
        owner_id=owner_id,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        telegram_proxy=proxy,
        force_ipv4=_bool_env("FORCE_IPV4"),
        telegram_timeout=timeout,
    )
