#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from _common import clear_turn_prompt, extract_user_turn, in_holo_repo, load_payload, load_rag_memory, load_turn_prompt


def thread_key_for(cwd: str | None) -> str:
    if not cwd:
        return "codex:holo"
    try:
        current = Path(cwd).resolve()
    except OSError:
        return "codex:holo"
    if current.name:
        return f"codex:{current.name}"
    return "codex:holo"


def main() -> int:
    payload = load_payload()
    if not in_holo_repo(payload.get("cwd")):
        return 0

    turn_id = str(payload.get("turn_id", "")).strip()
    query = extract_user_turn(load_turn_prompt(turn_id) or "")
    message = str(payload.get("last_assistant_message") or "").strip()
    if not query or not message:
        clear_turn_prompt(turn_id)
        return 0

    rag_memory = load_rag_memory()
    try:
        rag_memory.auto_observe_turn(
            query,
            reply=message,
            tags=["runtime", "hook_stop", "codex_cli"],
            source="codex.hook.stop",
            turn_id=turn_id,
            metadata={
                "channel": "codex_cli",
                "thread_key": thread_key_for(payload.get("cwd")),
                "message_id": turn_id,
                "chat_name": "Codex CLI",
                "sender": "user",
                "source_ref": str(payload.get("cwd", "")),
            },
        )
    except Exception:
        pass
    finally:
        clear_turn_prompt(turn_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
