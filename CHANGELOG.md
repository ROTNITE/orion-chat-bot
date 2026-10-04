# Changelog

## 1.1.5 — 2026-10-04

- Основной Windows launcher переписан на Python stdlib вместо PowerShell menu logic.
- Исправлена ошибка `You cannot call a method on a null-valued expression` при пустом выводе диагностики.
- Предварительная сетевая диагностика больше не блокирует запуск при временном timeout.
- Добавлена диагностика TG WS Proxy / MTProto и явное объяснение несовместимости MTProto proxy с HTTPS Bot API aiogram.
- Добавлены regression-тесты для пустого stdout диагностики и парсинга JSON.

## 1.1.4 — 2026-10-04

- Исправлена гонка между успешной сетевой диагностикой и следующим `getMe`: временный timeout больше не завершает Orion сразу.
- Добавлены повторные попытки для стартовых запросов Telegram; polling продолжает использовать backoff aiogram.
- `.env` теперь загружается по явному пути с `override=True`, поэтому сохранённый `FORCE_IPV4=1` действительно применяется к процессу бота.
- Диагностика делает до двух `getMe` и выводит понятный русский результат вместо сырого JSON.
- Убран `Test-NetConnection`, который загрязнял меню асинхронным progress-выводом; TCP 443 проверяется через `TcpClient` с таймаутом.
- Пункты меню 2/4/5/6/8 теперь показывают результат; добавлен пункт 9 для сброса сетевых настроек.
- Запуск тестов переведён на native-процесс и теперь явно печатает итог.

## 1.1.3 — 2026-10-04

- Исправлены `.cmd`: ASCII + CRLF без UTF-8 BOM, поэтому `cmd.exe` больше не видит `∩╗┐@echo off`.
- Orion запускается через `Start-Process -NoNewWindow -Wait`: stderr Python больше не превращается PowerShell в ложную фатальную ошибку.
- Полные необработанные исключения выводятся в консоль и записываются в `logs/orion.log` с ротацией.
- Перед polling автоматически удаляется старый webhook, чтобы он не конфликтовал с `getUpdates`.
- Добавлены регрессионные тесты формата Windows-лаунчеров и способа запуска процесса.

## 1.1.2 — 2026-10-04

- Исправлен критический Windows-баг: обычный INFO-лог Python больше не должен завершать launcher.
- Python logging направлен в stdout.

## 1.1.1 — Русский Windows-лаунчер

- Полностью переведены меню, первоначальная настройка, диагностика и сообщения об ошибках Windows-лаунчера на русский язык.
- Добавлена явная UTF-8-настройка консоли PowerShell для корректного отображения кириллицы.
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
