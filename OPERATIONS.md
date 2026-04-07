# Holo 入口与进程

继续开发或交接时，先读：
- `/home/ran_yakumo/holo/HOLO_HANDOFF.md`
- `/home/ran_yakumo/holo/HOLO_SYSTEM.md`
- `/home/ran_yakumo/holo/HOLO_DEVELOPMENT.md`

## 一键入口

- 全部启动：`/home/ran_yakumo/holo/scripts/holo-start-all.sh`
- 全部停止：`/home/ran_yakumo/holo/scripts/holo-stop-all.sh`
- 全部重开：`/home/ran_yakumo/holo/scripts/holo-restart-all.sh`
- 只看状态：`/home/ran_yakumo/holo/scripts/holo-status.sh`

## 拆开入口

- 只起 WSL 主脑：`/home/ran_yakumo/holo/scripts/holo-online.sh`
- 只停 WSL 主脑：`/home/ran_yakumo/holo/scripts/holo-offline.sh`
- 只起微信监听：
  - `/home/ran_yakumo/holo/windows_helper/start_holo_wechat.ps1`
- 只停微信监听：
  - `/home/ran_yakumo/holo/windows_helper/stop_holo_wechat.ps1`
  - `/home/ran_yakumo/holo/windows_helper/kill_watchers.ps1`

## 关键进程名

- WSL reply API：
  - `python3 -m holo_host --config /home/ran_yakumo/holo/.holo_host.toml serve-api`
- WSL daemon：
  - `python3 -m holo_host --config /home/ran_yakumo/holo/.holo_host.toml daemon`
- Windows 微信 watcher：
  - `pythonw.exe`
  - 脚本入口：`pyweixin_watcher.pyw`
  - 当前默认模式：`watch-live`
  - 当前 live 配置：`pyweixin_dialog`

## 关键文件

- WSL 配置：
  - `/home/ran_yakumo/holo/.holo_host.toml`
- WSL `reply_api` 在 Windows 桥接场景下应绑定 `0.0.0.0`；Windows helper 会在启动时把 runtime `agent_url` 重写到当前 WSL IP（若 localhost forwarding 不可用）。
- Codex CLI 归档 hooks：
  - `/home/ran_yakumo/holo/.codex/hooks.json`
  - `/home/ran_yakumo/holo/holo_memory_library/codex_hooks/user_prompt_submit.py`
  - `/home/ran_yakumo/holo/holo_memory_library/codex_hooks/stop_revise.py`
- 微信 live 配置：
  - `/home/ran_yakumo/holo/windows_helper/wechat_helper.live.json`
- 微信 transport 心跳：
  - `C:\\wechat-helper\\transport_state.live.json`
- 微信在线监听命令：
  - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-live`
  - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json wcf-info`
  - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-pyweixin-dialog`
- 微信维护/回退命令：
  - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-pyweixin`
  - `py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json watch-wcf`
- Windows watcher 日志：
  - `C:\\wechat-helper\\receipts\\pyweixin_watcher.log`
- 运行时日志目录：
  - `/home/ran_yakumo/holo/.holo_runtime/logs`
- 全量对话归档：
  - `/home/ran_yakumo/holo/holo_memory_library/memories/conversation_archive.jsonl`

## 命令行对话归档

- `holo` 仓里的 Codex CLI 对话会通过 repo-local hooks 自动写入全量归档
- 快速检查最近命令行 turn：
  - `python3 /home/ran_yakumo/holo/holo_memory_library/rag_memory.py show-archive --channel codex_cli --limit 5`
- 若这里突然没新纪录，优先检查：
  - `/.codex/hooks.json`
  - `holo_memory_library/codex_hooks/user_prompt_submit.py`
  - `holo_memory_library/codex_hooks/stop_revise.py`

## 拔盘前建议

1. 先执行：`/home/ran_yakumo/holo/scripts/holo-stop-all.sh`
2. 再执行：`/home/ran_yakumo/holo/scripts/holo-status.sh`
3. 确认 `reply_api`、`daemon` 都是 `stopped` 或 `stale pid file removed`
4. 再看 `transport` 一行是否已变成 `stopped` 或 `stale`
5. 再去停 WSL / 拔盘

## WCF 先验检查

- 先跑：`py -3 windows_helper\wechat_helper.py --config C:\wechat-helper\wechat_helper.json wcf-info`
- 若返回 `compatibility = incompatible`，说明当前这台微信客户端和已安装的 `wcferry` 代际不匹配，不要再硬起 live watcher
- 当前这台机器正是这种情况，所以在线主路已经改到 `pyweixin_dialog`

## Mind OS Diagnostics
- Graph DB:
  - `/home/holo/holo/.holo_runtime/mind_graph.sqlite3`
- Rebuild graph:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml backfill-mind-graph`
- Inspect one thread graph:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml inspect-graph --thread-key Nemoqi --chat-name Nemoqi`
- Trace recall:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml trace-recall --thread-key Nemoqi --chat-name Nemoqi --query "你还记得重新上线前吗"`
- Stream status:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-stream-status`
- Processor mesh tasks:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-processor-mesh`

## Memory Fabric Stage-1 Live Diagnostics
- Vector DB:
  - `/home/holo/holo/.holo_runtime/milvus/memory_fabric.db`
- Hybrid recall trace:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml trace-hybrid-recall --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "浣犺繕璁板緱閲嶆柊涓婄嚎鍓嶅悧"`
- Inspect mind packet:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml inspect-mind --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "你还记得重新上线前吗"`
- Activation state:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml show-activation-state --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- Vector health:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml vector-health`
- Stream tick:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml stream-tick --stream-name association_stream`
- Reply probe:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml reply-probe --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "浣犺繕璁板緱閲嶆柊涓婄嚎鍓嶅悧" --mode hybrid`
- Memory-fabric benchmark:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml benchmark-memory-fabric --thread-key Nemoqi --chat-name Nemoqi --channel wechat --query "你还记得重新上线前吗" --iterations 5 --warmup 1 --probe mind`
- Stage-1 acceptance gate:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml accept-memory-fabric-stage1 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`

说明：
- 如果 WSL `reply_api` 已在线，这些诊断会优先走 live HTTP 服务，而不是再起一个新的本地进程。
- 这样可以避免第二个进程再次打开 `/home/holo/holo/.holo_runtime/milvus/memory_fabric.db`，撞上 Milvus Lite 的本地文件占用。
