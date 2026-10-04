import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from .config import get_config
from .telegram_app import serve


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_dir = Path('logs')
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / 'orion.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


if __name__ == '__main__':
    config = get_config()
    _configure_logging(config.log_level)
    log = logging.getLogger('orion')
    try:
        asyncio.run(serve(config))
    except KeyboardInterrupt:
        log.info('Orion stopped by user (Ctrl+C).')
    except BaseException:
        # Keep the complete traceback on stdout and in logs/orion.log.  This avoids
        # Windows PowerShell turning only the first stderr line into a misleading [X].
        log.exception('Orion stopped because of an unhandled fatal error.')
        raise SystemExit(1)
