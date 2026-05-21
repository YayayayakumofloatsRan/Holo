# CLI UTF-8 Surrogate Guard Progress

Date: 2026-05-21

## Trigger

Interactive CLI chat could raise:

```text
UnicodeEncodeError: 'utf-8' codec can't encode characters ... surrogates not allowed
```

The failure can occur when a lone Unicode surrogate reaches a CLI JSON request body or a printed chat payload.

## Root Cause

The CLI intentionally uses `ensure_ascii=False` so Chinese and other user-facing text remains readable. That is correct for normal Unicode, but Python refuses to encode lone surrogate code points to UTF-8. A malformed input, provider response, or memory snapshot value can therefore crash the CLI at the transport/output boundary.

## Fix

- Added UTF-8-safe normalization helpers in `holo_host/cli.py`.
- Sanitized live API request payloads before UTF-8 encoding.
- Sanitized live API JSON responses before returning them to chat code.
- Sanitized chat response text and bubble text before printing.
- Sanitized interactive chat JSON output, including `/snapshot`.
- Sanitized local fallback replies before telemetry capture and printing.

Invalid lone surrogates are replaced with `?`. Valid Unicode, including Chinese text, is preserved.

## Verification

Targeted regression tests:

```text
pytest -q tests/test_cli_live_api.py -k surrogate --basetemp .holo_runtime\pytest-tmp
pytest -q tests/test_cli_chat.py -k "surrogate or snapshot or json_print" --basetemp .holo_runtime\pytest-tmp
```

Focused CLI test suite:

```text
pytest -q tests/test_cli_live_api.py tests/test_cli_chat.py --basetemp .holo_runtime\pytest-tmp
```

WSL smoke check:

```text
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 - <<'PY'
from holo_host import cli
s = 'bad-' + chr(0xd800) + '-x'
print(cli._chat_response_text({'text': s}))
print(cli._json_dumps_utf8_safe({'x': s}, ensure_ascii=False))
PY"
```

Expected smoke output:

```text
bad-?-x
{"x": "bad-?-x"}
```

Interactive WSL chat smoke:

```text
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && printf '%s\n%s\n' '回忆任何事情？' '/quit' | timeout 60 python3 -m holo_host chat --no-local-fallback --timeout 30"
```

Expected result: the CLI exits without `UnicodeEncodeError`. A slow live reply may still return `[error: live_http_unavailable]`, which is a live-processing timeout path rather than a Unicode encoding crash.
