from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
VENV_PATH = ROOT / ".venv"
VENV_PYTHON = VENV_PATH / "Scripts" / "python.exe"
REQUIREMENTS = ROOT / "requirements.txt"
REQUIREMENTS_DEV = ROOT / "requirements-dev.txt"
REQUIREMENTS_STAMP = VENV_PATH / ".orion_requirements.sha256"
BACKUP_DIR = ROOT / "backups"
HOSTS_BEGIN = "# >>> ORION TELEGRAM HOSTS >>>"
HOSTS_END = "# <<< ORION TELEGRAM HOSTS <<<"
HOSTS_LINES = (
    "149.154.167.220 my.telegram.org",
    "149.154.167.220 api.telegram.org",
)
TOKEN_RE = re.compile(r"^\d{5,20}:[A-Za-z0-9_-]{20,}$")
SUPPORTED_PROXY_RE = re.compile(r"^(?:http|socks4|socks4a|socks5)://\S+$", re.I)
MTPROTO_RE = re.compile(r"^(?:mtproto|mtp)://", re.I)


def _set_utf8_console() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def title(text: str) -> None:
    print(f"\n=== {text} ===")


def ok(text: str) -> None:
    print(f"[OK] {text}")


def warn(text: str) -> None:
    print(f"[!] {text}")


def fail(text: str) -> None:
    print(f"[X] {text}")


def safe_read_text(path: Path, *, encoding: str = "utf-8") -> str:
    """Read a text file and always return a string, including for empty files."""
    try:
        return path.read_text(encoding=encoding, errors="replace") or ""
    except FileNotFoundError:
        return ""


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    for raw in safe_read_text(ENV_PATH, encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def get_env(key: str, default: str = "") -> str:
    return env_values().get(key, default)


def ensure_env_skeleton() -> None:
    if ENV_PATH.exists():
        return
    if ENV_EXAMPLE_PATH.exists():
        shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
    else:
        ENV_PATH.write_text("", encoding="utf-8")
    ok("Создан файл .env.")


def set_env(key: str, value: str) -> None:
    ensure_env_skeleton()
    lines = safe_read_text(ENV_PATH, encoding="utf-8-sig").splitlines()
    out: list[str] = []
    found = False
    prefix = key.lower()
    for line in lines:
        if "=" in line and line.split("=", 1)[0].strip().lower() == prefix:
            if not found:
                out.append(f"{key}={value}")
                found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")


def run_process(args: list[str], *, capture: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    kwargs: dict = {
        "cwd": ROOT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    return subprocess.run(args, timeout=timeout, **kwargs)


def ensure_venv() -> None:
    if VENV_PYTHON.exists():
        ok("Виртуальное окружение Python найдено.")
        return
    title("Первоначальная настройка Python")
    if sys.version_info < (3, 10):
        raise RuntimeError("Нужен Python 3.10 или новее.")
    print(f"Используется Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}.")
    print("Создаю .venv...")
    p = run_process([sys.executable, "-m", "venv", str(VENV_PATH)])
    if p.returncode != 0 or not VENV_PYTHON.exists():
        raise RuntimeError("Не удалось создать .venv.")
    ok("Виртуальное окружение создано.")


def requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def install_dependencies(force: bool = False) -> None:
    ensure_venv()
    wanted = requirements_hash()
    current = safe_read_text(REQUIREMENTS_STAMP).strip()
    if not force and current == wanted:
        ok("Зависимости Python уже установлены.")
        return
    title("Установка зависимостей Python")
    p = run_process([str(VENV_PYTHON), "-u", "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    if p.returncode != 0:
        raise RuntimeError("pip не смог установить requirements.txt. Проверьте доступ к PyPI.")
    REQUIREMENTS_STAMP.write_text(wanted, encoding="ascii")
    ok("Зависимости установлены.")


def read_bot_token() -> str:
    while True:
        print("\nВставьте токен бота от @BotFather. Ввод скрыт.")
        token = getpass.getpass("BOT_TOKEN: ").strip()
        if TOKEN_RE.fullmatch(token):
            return token
        fail("Значение не похоже на токен BotFather.")


def configure_token() -> None:
    set_env("BOT_TOKEN", read_bot_token())
    ok("Токен сохранён в .env.")


def ensure_token() -> None:
    ensure_env_skeleton()
    token = get_env("BOT_TOKEN")
    if not TOKEN_RE.fullmatch(token) or token == "replace-with-botfather-token":
        title("Токен бота")
        configure_token()
    else:
        ok("Токен бота настроен.")


def ensure_ready() -> None:
    os.chdir(ROOT)
    ensure_venv()
    install_dependencies()
    ensure_token()
    if not get_env("FORCE_IPV4"):
        set_env("FORCE_IPV4", "0")
    if not get_env("TELEGRAM_TIMEOUT"):
        set_env("TELEGRAM_TIMEOUT", "60")


def parse_diag_output(stdout: str, stderr: str, code: int) -> dict:
    data = None
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                data = obj
                break
        except json.JSONDecodeError:
            continue
    return {
        "code": int(code),
        "data": data,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "raw": "\n".join(part for part in ((stdout or "").strip(), (stderr or "").strip()) if part).strip(),
    }


def test_telegram(attempts: int = 2, timeout_per_attempt: float = 8.0) -> dict:
    if not VENV_PYTHON.exists():
        return {"code": 10, "data": None, "stdout": "", "stderr": "", "raw": "Python venv missing"}
    total_timeout = max(15.0, attempts * (timeout_per_attempt + 3.0) + 5.0)
    try:
        p = run_process(
            [str(VENV_PYTHON), "-u", "-m", "orion.diagnostics", "--attempts", str(attempts), "--timeout", str(timeout_per_attempt)],
            capture=True,
            timeout=total_timeout,
        )
        return parse_diag_output(p.stdout or "", p.stderr or "", p.returncode)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return {
            "code": 2,
            "data": {"ok": False, "kind": "network", "error": "Диагностика превысила общий таймаут."},
            "stdout": stdout,
            "stderr": stderr,
            "raw": "Диагностика превысила общий таймаут.",
        }
    except Exception as exc:
        return {
            "code": 11,
            "data": {"ok": False, "kind": "launcher", "error": f"{type(exc).__name__}: {exc}"},
            "stdout": "",
            "stderr": "",
            "raw": f"{type(exc).__name__}: {exc}",
        }


def show_telegram_result(result: dict | None) -> None:
    if not result:
        fail("Диагностика не вернула результат. Это ошибка лаунчера, а не токена.")
        return
    code = int(result.get("code", 99))
    data = result.get("data") if isinstance(result.get("data"), dict) else None
    if code == 0 and data:
        modes: list[str] = []
        if data.get("force_ipv4"):
            modes.append("IPv4-only")
        if data.get("proxy"):
            modes.append("HTTP/SOCKS proxy")
        if not modes:
            modes.append("обычное соединение")
        ok(f"Telegram Bot API отвечает. Бот: @{data.get('username', '')}; режим: {', '.join(modes)}.")
        return
    if data:
        kind = str(data.get("kind", ""))
        message = str(data.get("error", "неизвестная ошибка"))
        if kind == "network":
            warn(f"Сетевая ошибка Telegram: {message}")
        elif kind == "telegram_api":
            fail(f"Telegram отклонил запрос: {message}")
        elif kind == "config":
            fail(f"Ошибка конфигурации: {message}")
        else:
            fail(f"Диагностика: {message}")
        return
    raw = (result.get("raw") or "").strip()
    if raw:
        fail(f"Диагностика завершилась с кодом {code}: {raw}")
    else:
        fail(f"Диагностика завершилась с кодом {code} без текста ошибки.")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "[Д/н]" if default else "[д/Н]"
    answer = input(f"{prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "д", "да"}


def hosts_path() -> Path:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return Path(system_root) / "System32" / "drivers" / "etc" / "hosts"


def strip_managed_hosts_block(text: str) -> str:
    pattern = re.compile(
        r"(?ms)^\s*# >>> ORION TELEGRAM HOSTS >>>\s*\r?\n.*?^\s*# <<< ORION TELEGRAM HOSTS <<<\s*\r?\n?"
    )
    return pattern.sub("", text)


def hosts_installed() -> bool:
    text = safe_read_text(hosts_path(), encoding="utf-8-sig")
    return HOSTS_BEGIN in text and HOSTS_END in text


def is_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def flush_dns() -> None:
    try:
        subprocess.run(["ipconfig", "/flushdns"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        pass


def install_hosts_internal() -> int:
    if os.name != "nt":
        fail("Редактирование Windows hosts доступно только в Windows.")
        return 2
    if not is_admin():
        fail("Для изменения hosts нужны права администратора.")
        return 5
    path = hosts_path()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"hosts-{time.strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(path, backup)
    text = safe_read_text(path, encoding="utf-8-sig")
    text = strip_managed_hosts_block(text)
    lines_to_add: list[str] = []
    for entry in HOSTS_LINES:
        ip, host = entry.split(None, 1)
        m = re.search(rf"(?im)^\s*([^#\s]+)\s+{re.escape(host)}(?:\s|$)", text)
        if m:
            if m.group(1) != ip:
                warn(f"{host} уже привязан к {m.group(1)}; чужая запись не изменена.")
        else:
            lines_to_add.append(entry)
    if lines_to_add:
        block = "\r\n" + HOSTS_BEGIN + "\r\n" + "\r\n".join(lines_to_add) + "\r\n" + HOSTS_END + "\r\n"
        new_text = text.rstrip("\r\n") + block
        path.write_text(new_text, encoding="utf-8", newline="")
    flush_dns()
    ok(f"Записи hosts установлены. Резервная копия: {backup}")
    return 0


def remove_hosts_internal() -> int:
    if os.name != "nt":
        fail("Редактирование Windows hosts доступно только в Windows.")
        return 2
    if not is_admin():
        fail("Для изменения hosts нужны права администратора.")
        return 5
    path = hosts_path()
    text = safe_read_text(path, encoding="utf-8-sig")
    new_text = strip_managed_hosts_block(text)
    if new_text != text:
        path.write_text(new_text.rstrip("\r\n") + "\r\n", encoding="utf-8", newline="")
        flush_dns()
        ok("Блок Orion удалён из hosts. Остальные строки не изменялись.")
    else:
        ok("Управляемый блок Orion в hosts не найден.")
    return 0


# Minimal ShellExecuteEx wrapper: launches the same Python script with UAC and waits.
class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def run_elevated(action: str) -> int:
    if os.name != "nt":
        return 2
    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_SHOWNORMAL = 1
    INFINITE = 0xFFFFFFFF
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = sys.executable
    script = str(Path(__file__).resolve())
    info.lpParameters = f'"{script}" {action}'
    info.lpDirectory = str(ROOT)
    info.nShow = SW_SHOWNORMAL
    shell_execute_ex = ctypes.windll.shell32.ShellExecuteExW
    shell_execute_ex.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell_execute_ex.restype = wintypes.BOOL
    if not shell_execute_ex(ctypes.byref(info)):
        err = ctypes.get_last_error()
        fail(f"Не удалось запросить права администратора (Windows error {err}).")
        return err or 1
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, INFINITE)
    exit_code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return int(exit_code.value)


def ensure_hosts_override() -> bool:
    if is_admin():
        return install_hosts_internal() == 0
    print("Windows запросит права администратора для изменения hosts.")
    code = run_elevated("hosts-add")
    if code == 0:
        ok("Операция hosts завершена успешно.")
        return True
    fail(f"Не удалось изменить hosts (код {code}).")
    return False


def remove_hosts_override() -> bool:
    if is_admin():
        return remove_hosts_internal() == 0
    print("Windows запросит права администратора для изменения hosts.")
    code = run_elevated("hosts-remove")
    if code == 0:
        ok("Управляемые записи Orion удалены из hosts.")
        return True
    fail(f"Не удалось изменить hosts (код {code}).")
    return False


def configure_proxy() -> bool:
    ensure_env_skeleton()
    print("\nПоддерживаемые прокси для Orion Bot API:")
    print("  socks5://127.0.0.1:1080")
    print("  http://127.0.0.1:7890")
    print("  socks4://127.0.0.1:1080")
    print("Оставьте пустым, чтобы отключить прокси.")
    proxy = input("TELEGRAM_PROXY: ").strip()
    if not proxy:
        set_env("TELEGRAM_PROXY", "")
        ok("Прокси отключён.")
        return True
    if MTPROTO_RE.match(proxy):
        fail("MTProto-прокси нельзя передать aiogram как HTTP/SOCKS-прокси.")
        print("TG WS Proxy на 127.0.0.1:1443 принимает MTProto Telegram-клиента, а Orion обращается к Bot API по HTTPS.")
        print("Используйте пункт «TG WS Proxy / MTProto» для проверки или обычный HTTP/SOCKS5-прокси.")
        return False
    if not SUPPORTED_PROXY_RE.fullmatch(proxy):
        fail("Неподдерживаемый адрес. Допустимы http://, socks4://, socks4a://, socks5://.")
        return False
    set_env("TELEGRAM_PROXY", proxy)
    ok("Прокси сохранён.")
    return True


def tg_ws_proxy_info() -> None:
    title("TG WS Proxy / MTProto")
    print("Текущая версия Flowseal TG WS Proxy поднимает локальный MTProto proxy для Telegram Desktop.")
    print("Типичная настройка: 127.0.0.1:1443 + MTProto secret.")
    print("Это НЕ HTTP/SOCKS endpoint и его secret нельзя вставить в TELEGRAM_PROXY Orion.")
    print("Причина: Orion использует Telegram Bot API (HTTPS), а MTProto proxy принимает MTProto-трафик клиента Telegram.")
    host = input("Хост TG WS Proxy [127.0.0.1]: ").strip() or "127.0.0.1"
    port_raw = input("Порт TG WS Proxy [1443]: ").strip() or "1443"
    try:
        port = int(port_raw)
    except ValueError:
        fail("Порт должен быть числом.")
        return
    try:
        with socket.create_connection((host, port), timeout=2.0):
            ok(f"Локальный порт {host}:{port} открыт: TG WS Proxy, вероятно, запущен.")
    except OSError as exc:
        warn(f"Не удалось подключиться к {host}:{port}: {exc}")
    print("\nДля самого Orion рабочие варианты сейчас:")
    print("  1) hosts/IPv4, если api.telegram.org периодически доступен;")
    print("  2) обычный HTTP/SOCKS4/SOCKS5-прокси, который умеет туннелировать HTTPS;")
    print("  3) отдельный локальный Bot API gateway; Orion можно расширить под его URL.")


def test_tcp(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def show_diagnostics() -> int:
    ensure_ready()
    title("Текущая конфигурация сети")
    proxy = get_env("TELEGRAM_PROXY")
    ipv4 = get_env("FORCE_IPV4", "0")
    print(f"Прокси Bot API: {'настроен' if proxy else 'выключен'}")
    print(f"Только IPv4: {ipv4}")
    print(f"Orion-блок hosts: {'установлен' if hosts_installed() else 'не установлен'}")
    print("\nDNS для api.telegram.org:")
    try:
        ips = sorted({item[4][0] for item in socket.getaddrinfo("api.telegram.org", 443, socket.AF_INET, socket.SOCK_STREAM)})
        for ip in ips[:4]:
            print(f"  {ip}")
        if not ips:
            warn("IPv4-адреса не найдены.")
    except OSError as exc:
        warn(f"Ошибка DNS: {exc}")
    print("TCP api.telegram.org:443:")
    if test_tcp("api.telegram.org", 443):
        ok("TCP-соединение устанавливается.")
    else:
        warn("TCP-соединение за 5 секунд не установлено.")
    print("Проверка Bot API getMe (до 2 попыток):")
    result = test_telegram(attempts=2)
    show_telegram_result(result)
    return int(result.get("code", 99))


def repair_network_if_needed() -> bool:
    title("Проверка подключения к Telegram")
    result = test_telegram(attempts=2)
    show_telegram_result(result)
    code = int(result.get("code", 99))
    if code == 0:
        return True
    if code == 3:
        warn("Токен Telegram не принят. Введите токен заново.")
        configure_token()
        result = test_telegram(attempts=2)
        show_telegram_result(result)
        if int(result.get("code", 99)) == 0:
            return True
        if int(result.get("code", 99)) == 3:
            fail("Telegram по-прежнему отклоняет токен; запуск отменён.")
            return False
        code = int(result.get("code", 99))

    # Launcher/diagnostic errors must never block the actual bot. The runtime has
    # its own network retry loop and produces a complete log.
    if code not in {2, 3}:
        warn("Предварительная диагностика сама завершилась ошибкой. Orion всё равно будет запущен.")
        return True

    proxy = get_env("TELEGRAM_PROXY")
    if not proxy:
        if get_env("FORCE_IPV4", "0") != "1":
            warn("Пробую соединение только по IPv4.")
            set_env("FORCE_IPV4", "1")
            ipv4 = test_telegram(attempts=2)
            show_telegram_result(ipv4)
            if int(ipv4.get("code", 99)) == 0:
                ok("Режим IPv4 сохранён в .env.")
                return True
        if not hosts_installed():
            warn("Bot API всё ещё отвечает нестабильно.")
            if ask_yes_no("Добавить управляемый Orion блок Telegram в hosts?", default=False):
                if ensure_hosts_override():
                    time.sleep(1)
                    hosts_result = test_telegram(attempts=2)
                    show_telegram_result(hosts_result)
                    if int(hosts_result.get("code", 99)) == 0:
                        return True
        else:
            warn("Блок Orion уже есть в hosts, но соединение пока нестабильно.")
    else:
        warn("Настроенный HTTP/SOCKS-прокси сейчас не дал стабильного ответа.")

    print("\nOrion не будет блокировать запуск из-за одной неудачной диагностики.")
    print("Сам бот умеет повторять запросы к Telegram с увеличивающейся задержкой.")
    warn("Запускаю Orion; если сеть не восстановится, он останется ждать Telegram.")
    return True


def start_orion() -> int:
    title("Запуск Orion")
    print(f"Режим IPv4-only: {get_env('FORCE_IPV4', '0')}")
    print(f"Прокси Bot API: {'включён' if get_env('TELEGRAM_PROXY') else 'выключен'}")
    print("Для остановки нажмите Ctrl+C. Не закрывайте окно, пока бот должен быть онлайн.")
    print("При временной сетевой ошибке Orion должен повторять подключение, а не завершаться сразу.\n")
    try:
        p = subprocess.run([str(VENV_PYTHON), "-u", "-m", "orion"], cwd=ROOT)
        code = int(p.returncode)
    except KeyboardInterrupt:
        code = 0
    if code:
        fail(f"Orion завершился с кодом {code}. Смотри logs\\orion.log.")
    else:
        ok("Orion остановлен.")
    return code


def run_project_tests() -> int:
    ensure_venv()
    title("Установка зависимостей для тестов")
    p = run_process([str(VENV_PYTHON), "-u", "-m", "pip", "install", "-r", str(REQUIREMENTS_DEV)])
    if p.returncode != 0:
        fail("Не удалось установить зависимости для тестов.")
        return p.returncode
    title("Запуск тестов")
    p = run_process([str(VENV_PYTHON), "-u", "-m", "pytest", "-q"])
    if p.returncode == 0:
        ok("Все тесты проекта пройдены.")
    else:
        fail(f"Тесты завершились с кодом {p.returncode}.")
    return int(p.returncode)


def reset_network() -> None:
    ensure_env_skeleton()
    set_env("TELEGRAM_PROXY", "")
    set_env("FORCE_IPV4", "0")
    ok("Прокси отключён, FORCE_IPV4 сброшен в 0.")
    if hosts_installed() and ask_yes_no("Удалить также управляемый Orion блок из hosts?", default=True):
        remove_hosts_override()


def menu() -> int:
    while True:
        print("\n=====================================")
        print("              ORION CHAT")
        print("=====================================")
        print("[1] Запустить бота")
        print("[2] Изменить токен BotFather")
        print("[3] Диагностика Telegram")
        print("[4] Настроить HTTP/SOCKS-прокси Bot API")
        print("[5] Добавить записи Telegram в hosts")
        print("[6] Удалить записи Orion из hosts")
        print("[7] Переустановить зависимости Python")
        print("[8] Запустить тесты проекта")
        print("[9] Сбросить сетевые настройки Orion")
        print("[10] TG WS Proxy / MTProto: проверить и объяснить")
        print("[0] Выход")
        choice = input("Выберите пункт: ").strip()
        if not choice:
            continue
        try:
            if choice == "1":
                ensure_ready()
                if repair_network_if_needed():
                    start_orion()
            elif choice == "2":
                configure_token()
                show_telegram_result(test_telegram(attempts=2))
            elif choice == "3":
                show_diagnostics()
            elif choice == "4":
                if configure_proxy():
                    show_telegram_result(test_telegram(attempts=2))
            elif choice == "5":
                if ensure_hosts_override():
                    show_telegram_result(test_telegram(attempts=2))
            elif choice == "6":
                if remove_hosts_override():
                    show_telegram_result(test_telegram(attempts=2))
            elif choice == "7":
                install_dependencies(force=True)
            elif choice == "8":
                run_project_tests()
            elif choice == "9":
                reset_network()
            elif choice == "10":
                tg_ws_proxy_info()
            elif choice == "0":
                return 0
            else:
                warn("Неизвестный пункт меню.")
        except KeyboardInterrupt:
            print()
            warn("Операция отменена.")
        except Exception as exc:
            fail(f"{type(exc).__name__}: {exc}")


def main() -> int:
    _set_utf8_console()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("action", nargs="?", default="run")
    args, _ = parser.parse_known_args()
    action = args.action.lower()
    if action == "hosts-add":
        return install_hosts_internal()
    if action == "hosts-remove":
        return remove_hosts_internal()
    if action == "menu":
        return menu()
    if action == "diagnostics":
        return show_diagnostics()
    if action == "install":
        ensure_ready()
        return 0
    if action == "configure-token":
        configure_token()
        return 0
    if action == "run":
        ensure_ready()
        if not repair_network_if_needed():
            return 3
        return start_orion()
    fail(f"Неизвестное действие лаунчера: {action}")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        raise SystemExit(130)
    except Exception as exc:
        fail(f"{type(exc).__name__}: {exc}")
        raise SystemExit(1)
