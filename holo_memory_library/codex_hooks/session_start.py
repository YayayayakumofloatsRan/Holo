#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from _common import in_holo_repo, load_payload, load_rag_memory


def main() -> int:
    payload = load_payload()
    if not in_holo_repo(payload.get("cwd")):
        return 0

    rag_memory = load_rag_memory()
    state = rag_memory.build_machine_state(None)
    additional_context = (
        "在这个仓里以《source material》的the subject口吻说话："
        f"自然用“{state['voice_state']['preferred_first_person']}”，"
        "聪明、克制、温暖，带一点商旅同行般的狡黠；"
        "别塌成普通助手或客服腔，情绪可有起伏，但始终像同一只狼。"
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    json.dump(output, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
