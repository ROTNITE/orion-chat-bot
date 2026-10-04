# Windows one-click launcher

## START_ORION.cmd

Double-click `START_ORION.cmd`.

On the first run it:

1. finds Python 3.10+;
2. creates `.venv` if needed;
3. installs `requirements.txt` only when the requirements hash changes;
4. creates `.env` from `.env.example`;
5. asks for the BotFather token with hidden input and writes it to `.env`;
6. calls Telegram `getMe` before starting the long-polling bot;
7. if the direct connection fails, tries IPv4-only mode;
8. optionally offers an Orion-managed `hosts` block and then an HTTP/SOCKS proxy;
9. starts `python -m orion`.

On later runs, completed setup steps are skipped.

## ORION_MENU.cmd

The maintenance menu can:

- start Orion;
- replace the BotFather token;
- run DNS/TCP/Bot API diagnostics;
- set or clear `TELEGRAM_PROXY`;
- install the managed Telegram hosts block;
- remove only the managed hosts block;
- reinstall dependencies;
- run the project test suite.

Supported proxy examples:

```text
socks5://127.0.0.1:1080
http://127.0.0.1:7890
```

Proxy support uses aiogram's `AiohttpSession` and `aiohttp-socks`.

## hosts behavior

The launcher never rewrites the whole file intentionally. When the user explicitly enables the fallback it creates a backup under `backups/` and inserts only a marked block:

```text
# >>> ORION TELEGRAM HOSTS >>>
149.154.167.220 my.telegram.org
149.154.167.220 api.telegram.org
# <<< ORION TELEGRAM HOSTS <<<
```

If either hostname already has an active mapping outside Orion's block, Orion leaves that user-managed mapping untouched and warns instead of replacing it.

`REMOVE_ORION_HOSTS.cmd` removes only the marked Orion block and flushes the Windows DNS cache. It does not restore an old full-file backup over unrelated later edits.

A static Telegram IP is only a fallback and can become stale. The launcher therefore does **not** add it when the normal Bot API connection works.

## .env network options

```dotenv
TELEGRAM_PROXY=
FORCE_IPV4=0
TELEGRAM_TIMEOUT=60
```

- `TELEGRAM_PROXY` accepts `http://`, `socks4://`, `socks4a://` or `socks5://` URLs.
- `FORCE_IPV4=1` forces direct aiohttp connections to IPv4. It is ignored for proxy connectors.
- `TELEGRAM_TIMEOUT` is the Bot API request timeout in seconds.

The bot token remains plaintext in `.env` because the bot must be able to read it unattended. `.env` is excluded by `.gitignore`; do not publish or send it to other people.
