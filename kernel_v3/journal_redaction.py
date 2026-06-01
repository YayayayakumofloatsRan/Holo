from __future__ import annotations

from kernel_v3.context.redaction import Redactor
from kernel_v3.context.validator import deterministic_hash
from kernel_v3.contracts import JsonObject


_JOURNAL_REDACTOR = Redactor()


def redact_journal_data(data: JsonObject) -> JsonObject:
    redacted, markers = _JOURNAL_REDACTOR.redact(data)
    if not markers:
        return data
    safe = dict(redacted) if isinstance(redacted, dict) else {"value": redacted}
    existing = safe.get("redaction")
    redaction = dict(existing) if isinstance(existing, dict) else {}
    redaction["journal_data"] = "secret_like_fields_redacted"
    redaction["markers"] = sorted(markers)
    redaction["raw_data_hash"] = deterministic_hash(data)
    safe["redaction"] = redaction
    return safe
