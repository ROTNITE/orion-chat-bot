"""Static and stdlib-only checks for the Windows launcher."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile

ROOT = Path(__file__).parent.parent
LAUNCHER = ROOT / "tools" / "launcher.py"


def _load_launcher():
    spec = spec_from_file_location("orion_launcher", LAUNCHER)
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_launcher_files_exist():
    for name in ("START_ORION.cmd", "ORION_MENU.cmd", "REMOVE_ORION_HOSTS.cmd", "tools/launcher.py"):
        assert (ROOT / name).is_file(), name


def test_hosts_block_is_managed_and_exact():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "# >>> ORION TELEGRAM HOSTS >>>" in text
    assert "# <<< ORION TELEGRAM HOSTS <<<" in text
    assert "149.154.167.220 my.telegram.org" in text
    assert "149.154.167.220 api.telegram.org" in text
    assert "ipconfig" in text and "/flushdns" in text


def test_token_not_hardcoded_and_http_socks_proxy_supported():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "getpass.getpass" in text
    assert "TELEGRAM_PROXY" in text
    assert "FORCE_IPV4" in text
    assert "socks5" in text and "http" in text
    assert "aiohttp-socks" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_mtproto_is_explained_not_misrepresented_as_bot_api_proxy():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "TG WS Proxy / MTProto" in text
    assert "MTProto-прокси нельзя передать aiogram" in text
    assert "Bot API по HTTPS" in text


def test_runtime_uses_shared_network_builder():
    text = (ROOT / "orion/telegram_app.py").read_text(encoding="utf-8")
    assert "from .network import create_bot" in text
    assert "bot=create_bot(config)" in text


def test_cmd_wrappers_are_windows_safe_ascii_crlf_without_bom():
    for name in ("START_ORION.cmd", "ORION_MENU.cmd", "REMOVE_ORION_HOSTS.cmd"):
        data = (ROOT / name).read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf"), f"{name} has UTF-8 BOM"
        assert all(byte < 128 for byte in data), f"{name} must stay ASCII-only"
        assert b"\r\n" in data, f"{name} must use CRLF"
        assert b"\n" not in data.replace(b"\r\n", b""), f"{name} has bare LF"
        assert b"tools\\launcher.py" in data


def test_empty_diagnostic_file_reader_is_null_safe():
    launcher = _load_launcher()
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "empty.txt"
        path.write_bytes(b"")
        assert launcher.safe_read_text(path) == ""


def test_diag_parser_handles_empty_stdout_without_exception():
    launcher = _load_launcher()
    result = launcher.parse_diag_output("", "network timeout", 2)
    assert result["code"] == 2
    assert result["data"] is None
    assert "network timeout" in result["raw"]


def test_diag_parser_finds_json_last_line():
    launcher = _load_launcher()
    result = launcher.parse_diag_output('noise\n{"ok": true, "username": "x"}\n', "", 0)
    assert result["data"]["ok"] is True
    assert result["data"]["username"] == "x"


def test_launcher_does_not_block_runtime_on_internal_diag_failure():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "Предварительная диагностика сама завершилась ошибкой. Orion всё равно будет запущен." in text
    assert "Запускаю Orion; если сеть не восстановится" in text


def test_python_fatal_errors_are_logged_to_stdout_and_file():
    text = (ROOT / "orion/__main__.py").read_text(encoding="utf-8")
    assert "StreamHandler(sys.stdout)" in text
    assert "RotatingFileHandler" in text
    assert "logs" in text and "orion.log" in text
    assert "log.exception" in text


def test_project_env_overrides_stale_parent_environment():
    text = (ROOT / "orion/config.py").read_text(encoding="utf-8")
    assert "dotenv_path=ENV_PATH" in text
    assert "override=True" in text


def test_startup_retries_transient_telegram_network_errors():
    text = (ROOT / "orion/telegram_app.py").read_text(encoding="utf-8")
    assert "async def _telegram_retry" in text
    assert "except TelegramNetworkError" in text
    assert "await _telegram_retry('getMe'" in text
    assert "await _telegram_retry('deleteWebhook'" in text
