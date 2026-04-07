#!/usr/bin/env python3
from __future__ import annotations

from _common import extract_user_turn, in_holo_repo, load_payload, store_turn_prompt


def main() -> int:
    payload = load_payload()
    if not in_holo_repo(payload.get("cwd")):
        return 0

    prompt = extract_user_turn(str(payload.get("prompt", "")).strip())
    if not prompt:
        return 0
    store_turn_prompt(str(payload.get("turn_id", "")).strip(), prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
