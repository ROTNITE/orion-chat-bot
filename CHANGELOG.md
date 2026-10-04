# Changelog

## 1.1.0 — Windows one-click launcher

- Added `START_ORION.cmd` for first-run setup and normal startup.
- Added `ORION_MENU.cmd` for token, proxy, hosts, diagnostics, dependency reinstall and tests.
- Added `REMOVE_ORION_HOSTS.cmd` to remove only Orion-managed hosts entries.
- Added hidden BotFather token prompt and automatic `.env` creation.
- Added live `getMe` connectivity diagnostics before polling starts.
- Added `TELEGRAM_PROXY`, `FORCE_IPV4` and `TELEGRAM_TIMEOUT` settings.
- Added aiogram HTTP/SOCKS proxy support through `aiohttp-socks`.
- Added optional IPv4-only direct connection fallback.
- Added optional managed Windows hosts fallback with backup and DNS flush.
- Added launcher documentation and static tests.
