from __future__ import annotations

import argparse
import contextlib
import sys
import time
import traceback
from pathlib import Path

from wechat_helper import command_watch_live, load_config, write_transport_state


def log_path_from_config(config_path: str | None) -> Path:
    config = load_config(config_path)
    return config.receipt_dir / "pyweixin_watcher.log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hidden Windows-side live watcher for Holo WeChat transport")
    parser.add_argument("--config", default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-messages", type=int, default=0)
    args = parser.parse_args(argv)

    log_path = log_path_from_config(args.config)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("a", encoding="utf-8") as log_handle:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        config = load_config(args.config)
        mode = config.watch_mode
        write_transport_state(
            config,
            status="starting",
            mode="supervisor",
            transport=mode,
            detail="watcher supervisor booting",
        )
        log_handle.write(f"[{timestamp}] starting live watcher mode={mode} once={args.once} max_messages={args.max_messages}\n")
        log_handle.flush()
        while True:
            with contextlib.redirect_stdout(log_handle), contextlib.redirect_stderr(log_handle):
                try:
                    rc = command_watch_live(args.config, once=args.once, max_messages=args.max_messages)
                    if args.once:
                        write_transport_state(
                            config,
                            status="stopped",
                            mode="supervisor",
                            transport=mode,
                            detail=f"watcher exited rc={rc}",
                        )
                        return rc
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    write_transport_state(
                        config,
                        status="restarting",
                        mode="supervisor",
                        transport=mode,
                        detail=f"watcher loop exited rc={rc}",
                    )
                    log_handle.write(f"[{timestamp}] watcher loop exited rc={rc}, restarting\n")
                    log_handle.flush()
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    if args.once:
                        write_transport_state(
                            config,
                            status="degraded",
                            mode="supervisor",
                            transport=mode,
                            detail="watcher crashed",
                            error_type="Exception",
                        )
                        return 1
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    write_transport_state(
                        config,
                        status="degraded",
                        mode="supervisor",
                        transport=mode,
                        detail="watcher crashed, backing off",
                        error_type="Exception",
                    )
                    log_handle.write(f"[{timestamp}] watcher crashed, restarting after backoff\n")
                    log_handle.flush()
            time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
