# Stage16 Engineering Handoff

## What Landed

- Direction-aware helper artifact path conversion in `holo_host/reply_api.py`.
- Endpoint-topology WSL fallback in `windows_helper/wechat_helper.py`.
- Deterministic Stage14 replay metric rounding with raw aggregate metrics preserved.
- Local deterministic Stage12 acceptance appraisal that does not require live processor generation.
- `accept-stage16` CLI/API release-readiness gate.
- UTF-8 readable policy defaults and autobiographical outcome update text.

## Rerun Commands

- `pytest -q`
- `pytest -q tests/test_stage12_acceptance.py tests/test_stage14_replay.py tests/test_stage16_release.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage12`
- `python -m holo_host --config .holo_host.example.toml accept-stage14`
- `python -m holo_host --config .holo_host.example.toml accept-stage16`

Use `--skip-pytest` with `accept-stage16` only for quick diagnostics; the release gate expects the full check.

## Contracts To Preserve

- `/ingest-artifact` and host-side artifact ingestion consume Holo-host-facing `/mnt/<drive>/...` paths.
- Windows helper execution paths can still be converted to `X:\...` explicitly when needed.
- WSL fallback must not depend on the host OS running the test; localhost topology is the gate.
- Stage12 acceptance can use deterministic stub evidence, but normal `/reply` must keep live runtime behavior.
- Stage14 fixtures remain the replay baseline; raw metrics and display-rounded metrics must not silently drift apart.

## Rollback Notes

If Stage16 fails during shadow launch, stop host/helper processes and roll back the Stage16 commit. No database migration or runtime state contract change is required.
