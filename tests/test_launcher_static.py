"""Static checks for the Windows launcher; no PowerShell runtime is required."""
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_launcher_files_exist():
    for name in ("START_ORION.cmd", "ORION_MENU.cmd", "REMOVE_ORION_HOSTS.cmd", "tools/setup_orion.ps1"):
        assert (ROOT / name).is_file(), name


def test_hosts_block_is_managed_and_exact():
    text = (ROOT / "tools/setup_orion.ps1").read_text(encoding="utf-8-sig")
    assert "# >>> ORION TELEGRAM HOSTS >>>" in text
    assert "# <<< ORION TELEGRAM HOSTS <<<" in text
    assert "149.154.167.220 my.telegram.org" in text
    assert "149.154.167.220 api.telegram.org" in text
    assert "ipconfig /flushdns" in text


def test_token_not_hardcoded_and_proxy_supported():
    text = (ROOT / "tools/setup_orion.ps1").read_text(encoding="utf-8-sig")
    assert "Read-Host \"BOT_TOKEN\" -AsSecureString" in text
    assert "TELEGRAM_PROXY" in text
    assert "FORCE_IPV4" in text
    assert "aiohttp-socks" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_runtime_uses_shared_network_builder():
    text = (ROOT / "orion/telegram_app.py").read_text(encoding="utf-8")
    assert "from .network import create_bot" in text
    assert "bot=create_bot(config)" in text
