from __future__ import annotations

from types import SimpleNamespace

from kernel_v3 import cli
import kernel_v3.finance.tool_workers as tool_workers
from kernel_v3.finance.tool_workers import (
    build_finance_tool_worker_status,
    render_finance_tool_worker_status,
    write_finance_tool_worker_setup,
)
from kernel_v3.journal import JournalStore


def test_finance_tool_worker_status_lists_required_isolated_workers(monkeypatch, tmp_path) -> None:
    def fake_isolated_component_status(component: str):
        return {
            "component": component,
            "configured": False,
            "package_available": None,
            "python": None,
            "package_probe_error": None,
        }

    monkeypatch.setattr(tool_workers, "isolated_component_status", fake_isolated_component_status)

    payload = build_finance_tool_worker_status(root=tmp_path)
    workers = {item["worker_id"]: item for item in payload["workers"]}

    assert payload["schema"] == "holo.kernel_v3.finance_tool_workers.v1"
    assert payload["status"] == "attention"
    assert set(workers) == {"documents", "market"}
    assert workers["documents"]["component"] == "docling"
    assert workers["documents"]["requirements"] == "requirements-finance-isolated-documents.txt"
    assert workers["market"]["component"] == "openbb"
    assert workers["market"]["requirements"] == "requirements-finance-isolated-market.txt"
    assert "export HOLO_DOCLING_PYTHON=" in workers["documents"]["export_command"]
    assert "pip install -r requirements-finance-isolated-market.txt" in " ".join(workers["market"]["setup_commands"])


def test_finance_tool_worker_status_accepts_ready_configured_workers(monkeypatch, tmp_path) -> None:
    def fake_isolated_component_status(component: str):
        return {
            "component": component,
            "configured": True,
            "package_available": True,
            "python": f"/workers/{component}/bin/python",
            "package_probe_error": None,
        }

    monkeypatch.setattr(tool_workers, "isolated_component_status", fake_isolated_component_status)

    payload = build_finance_tool_worker_status(root=tmp_path)

    assert payload["status"] == "ok"
    assert payload["missing_workers"] == []
    assert all(item["ready"] for item in payload["workers"])
    assert "Finance tool workers: ok" in render_finance_tool_worker_status(payload)


def test_finance_tool_workers_cli_returns_status_payload(monkeypatch, tmp_path) -> None:
    def fake_isolated_component_status(component: str):
        return {
            "component": component,
            "configured": False,
            "package_available": None,
            "python": None,
            "package_probe_error": None,
        }

    monkeypatch.setattr(tool_workers, "isolated_component_status", fake_isolated_component_status)
    args = SimpleNamespace(
        bench_command="finance-tool-workers",
        root=str(tmp_path),
        format="json",
    )

    payload = cli._bench_command(args, JournalStore.in_memory())

    assert payload["schema"] == "holo.kernel_v3.finance_tool_workers.v1"
    assert payload["status"] == "attention"
    assert payload["missing_workers"] == ["documents", "market"]


def test_finance_tool_worker_setup_writes_reviewable_artifacts(tmp_path) -> None:
    artifact = write_finance_tool_worker_setup(root=tmp_path)

    script = tmp_path / "setup-finance-workers.sh"
    env_file = tmp_path / "finance-workers.env"

    assert artifact["status"] == "written"
    assert artifact["script_path"] == str(script)
    assert artifact["env_path"] == str(env_file)
    assert script.exists()
    assert env_file.exists()
    assert "requirements-finance-isolated-documents.txt" in script.read_text(encoding="utf-8")
    assert "requirements-finance-isolated-market.txt" in script.read_text(encoding="utf-8")
    assert "export HOLO_DOCLING_PYTHON=" in env_file.read_text(encoding="utf-8")
    assert "export HOLO_OPENBB_PYTHON=" in env_file.read_text(encoding="utf-8")


def test_finance_tool_workers_cli_can_write_setup_artifacts(monkeypatch, tmp_path) -> None:
    def fake_isolated_component_status(component: str):
        return {
            "component": component,
            "configured": False,
            "package_available": None,
            "python": None,
            "package_probe_error": None,
        }

    monkeypatch.setattr(tool_workers, "isolated_component_status", fake_isolated_component_status)
    args = SimpleNamespace(
        bench_command="finance-tool-workers",
        root=str(tmp_path),
        write_setup=True,
        format="json",
    )

    payload = cli._bench_command(args, JournalStore.in_memory())

    assert payload["setup_artifacts"]["status"] == "written"
    assert (tmp_path / "setup-finance-workers.sh").exists()
    assert (tmp_path / "finance-workers.env").exists()
