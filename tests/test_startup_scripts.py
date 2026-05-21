from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_script(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_powershell_start_scripts_gate_wechat_transport() -> None:
    for path in ("scripts/holo-start-all.ps1", "scripts/holo-wsl-start-all.ps1"):
        text = _read_script(path)
        assert "[switch]$WithWeChat" in text
        assert "HOLO_START_WECHAT" in text
        assert "if ($startWeChat)" in text
        assert "WeChat watcher not started" in text


def test_bash_start_script_gates_wechat_transport() -> None:
    text = _read_script("scripts/holo-start-all.sh")
    assert "HOLO_START_WECHAT" in text
    assert "start_holo_wechat.ps1" in text
    assert "WeChat watcher not started" in text
