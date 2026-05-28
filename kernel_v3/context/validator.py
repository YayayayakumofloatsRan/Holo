from __future__ import annotations

import hashlib
import json


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic_hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify_hash(payload: object, payload_hash: str) -> bool:
    return deterministic_hash(payload) == payload_hash
