from __future__ import annotations

from typing import Any


def show_action_calibration(
    self: Any,
    *,
    thread_key: str | None = None,
    chat_name: str | None = None,
    channel: str = "wechat",
    action_type: str | None = None,
    scenario_bucket: str | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    with self._memory_lock:
        return self.memory.show_action_calibration(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            action_type=action_type,
            scenario_bucket=scenario_bucket,
            limit=limit,
        )


def trace_outcome_history(
    self: Any,
    *,
    thread_key: str | None = None,
    chat_name: str | None = None,
    channel: str = "wechat",
    action_type: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    with self._memory_lock:
        return self.memory.trace_outcome_history(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            action_type=action_type,
            limit=limit,
        )


def trace_action_prediction_error(
    self: Any,
    *,
    thread_key: str | None = None,
    chat_name: str | None = None,
    channel: str = "wechat",
    action_type: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    with self._memory_lock:
        return self.memory.trace_action_prediction_error(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            action_type=action_type,
            limit=limit,
        )


def replay_calibration_fixture(
    self: Any,
    *,
    source_type: str = "synthetic_fixture",
    fixture_path: str | None = None,
    thread_key: str | None = None,
    chat_name: str | None = None,
    channel: str = "wechat",
    limit: int = 8,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    with self._memory_lock:
        return self.memory.replay_calibration_fixture(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
        )


def replay_policy_regret(
    self: Any,
    *,
    source_type: str = "synthetic_fixture",
    fixture_path: str | None = None,
    thread_key: str | None = None,
    chat_name: str | None = None,
    channel: str = "wechat",
    limit: int = 8,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    with self._memory_lock:
        return self.memory.replay_policy_regret(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            artifact_dir=artifact_dir,
        )
