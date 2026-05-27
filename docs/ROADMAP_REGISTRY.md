# Roadmap Registry

This registry exists so Holo planning does not collapse into a single forced choice every stage.

## Primary Track
- autobiographical continuity
- long-horizon goals
- identity/goal-led deliberation

## Secondary Tracks
- richer desire shaping
- stronger negotiated will

## Implemented Subject-Runtime Arc

This arc follows Stage17 thread-resident realtime runtime. Its purpose is to make Holo more continuous without turning continuity into a second brain or an unbounded loop.

Stage18: dual-speed reflex and predictive continuity
- Implemented bounded next-turn predictive continuity inside `ActiveThreadState`.
- Uses existing `micro_fast` only as a conservative generation lane after action-market selection.
- Keeps explicit memory/history/factual requests on recall escalation paths.

Stage19: bounded background continuity and attention frontier
- Implemented as a bounded Mind Graph `attention_frontier` fed only by `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`.
- Ingress hydrates same-thread active state from one frontier row before heavier recall.
- Bound entries by count, expiry, evidence refs, and canonical thread key; do not expand initiative sending rights.

Stage20: temporal commitments and interruption recovery
- Implemented as bounded Mind Graph `temporal_subject_state` plus `QueueStore.jobs` dedupe.
- Persists deferrals, promises, interrupted actions, restart-safe resume candidates, and due followup keys by canonical thread key.
- Routes recovery through action-market candidate metadata; temporal state never sends directly.

Stage21: policy sedimentation and negotiated will
- Implemented as Mind Graph `policy_sediment` rows with candidate/promoted/rejected/rolled-back statuses.
- Promotion is replay-gated and support/confidence/evidence bounded.
- Promoted rows bias action-market scoring only; hard policy gates, send permission, owner shutdown, secrets, auth, and safety boundaries remain outside sediment scope.

Stage22: bounded blackbox online canary
- Implemented as host-side `shadow` by default with `canary_live` behind whitelist, rate limits, rollback switch, and existing outbound policy.
- Records operational `online_canary_traces` and artifacts for daily Stage14 replay-on-live-artifacts.
- Hydrates bounded Mind Graph `world_coupling_signal` cues as same-thread perception inputs only; cues do not select actions or trigger recall by themselves.

Stage23: kernel/shell orthogonalization and release parity
- Implemented as a semantic-versus-delivery split: Stage22 suppression no longer rewrites the subject action contract and instead only changes transport-facing `returned_action` plus delivery fields.
- Restores full-green release parity by making artifact ingest backward-compatible again and by pushing replay gating onto raw metrics while rounded aggregates stay reporting-only.
- Keeps Stage22 shadow-first safety boundaries, live-artifact replay, rollback, rate limits, and canary traces intact.

Stage24: scene-state continuity layer
- Implemented as a bounded per-thread `scene_state` stored inside `active_thread_state`.
- Makes ordinary short turns prefer compact scene summaries and response sketches before verbatim history while keeping explicit memory/history/factual turns on escalation paths.
- Adds inspectable scene diagnostics and bounded scene deltas in action-market scoring without introducing a second brain or a new always-on loop.

Stage25: dense continuity scheduler and working set
- Implemented as a bounded `dense_working_set` plus `thread_pulse_trace` rebuilt only from `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`.
- Keeps a small hot-thread working set warm between turns, applies inspectable per-thread pulse budgets and cooldowns, and hydrates ingress before heavier recall.
- Does not add a new loop family, watcher-side decision logic, or background heavy recall.

Stage26: bounded task-world state
- Implemented as bounded Mind Graph `task_world_object` plus `task_world_link` storage for file, task, schedule, image-summary, and person objects.
- Keeps Stage22 `world_coupling_signal` as a compatibility projection while same-thread ingress hydrates from explicit task-world objects before heavier recall.
- Links temporal commitments and resume pressure into inspectable task-world state without adding a new decision layer or heavy-recall trigger.

Stage27: long-horizon blackbox soak and blind evaluation harness
- Implemented as an observational `QueueStore` soak-run surface plus artifact export under the Stage22 canary tree.
- Computes long-horizon scorecards, replays live artifacts, and exports blind transcript or comparison packets without mutating self-memory or widening runtime autonomy.
- Keeps online long-horizon canary deferred; Stage27 is replay-first and operational-only.

Stage28: multimodal homeostatic kernel
- Implemented as bounded packet-derived `visual_field`, `situational_field`, and `stage28` surfaces over existing visual memory, scene state, dense continuity, task-world state, temporal pressure, and homeostatic/affective pressure.
- Preserves richer image-understanding metadata and renders situational grounding before verbatim history for ordinary hot-path turns.
- Adds inspectable action-market `stage28_delta`, `stage28_rationale`, and `stage28_grounding_order` without adding a second brain, loop family, or transport decision path.

## Implemented Trust And Grounding Optimization Track

Stage139: tool calling maturity
- Implemented normalized `tool_observation_ledger` propagation, visible tool-claim grounding, deterministic tool-need classification, rejected-tool reentry, and a tool benchmark.
- Preserves WSL main-brain execution authority: provider output may propose tools, but only local observations count as proof that a tool ran.

Stage140: memory answer grounding
- Implemented normalized `memory_observation_ledger` propagation and visible memory-claim grounding.
- Confident recall language is repaired when memory sources are missing, weak, or contradicted.
- Stage135 topology can render actual memory observation nodes.

Stage141: memory claim alignment
- Implemented deterministic source-sufficiency checks for visible memory details.
- Source-exists-but-wrong-detail claims are marked unsupported, weak claims are bounded, and contradiction flags dominate.
- Stage135 topology can render a memory alignment gate and claim nodes without adding memory writes, provider calls, or transport authority.

Stage142: A' to A'' semantic novelty gate
- Implemented deterministic visible-bubble novelty, contradiction, and grounding gates over Stage132 progressive streams.
- Duplicate or low-value A'' segments are suppressed, prefix duplicates are trimmed, and valid tool feedback or memory limitations still emit.
- Stage139, Stage140, and Stage141 failures cannot be reintroduced by continuation bubbles; Stage135 topology can render a compact semantic novelty gate.

Stage143: packet budget and stop-reason report
- Implemented deterministic packet-chain observability over Stage132 and Stage142.
- Reports why fast/deep packets were sent or skipped, why continuation stopped, estimated token/timing cost, and grounding or novelty outcomes linked to the stop reason.
- Stage143 does not add provider calls, memory writes, tool execution, transport authority, or a second loop; Stage135 topology can render a compact packet-budget gate.

Stage144: context economy and packet policy calibration
- Implemented deterministic shadow diagnostics over Stage139-143 evidence.
- Reports bounded working-set slots, context sufficiency, context waste, and a recommended deep-packet policy: `keep`, `skip`, `defer`, `tool_first`, or `memory_first`.
- Stage144 does not enforce recommendations, add provider calls, write memory, execute tools, widen transport authority, or add a second loop; Stage135 topology can render a compact context-economy gate.

Stage145: predictive outcome and reaction kernel shadow
- Implemented deterministic prediction-error appraisal over Stage139-144 evidence.
- Reports predicted user need, best expected outcome, observed grounding/novelty/packet waste, and bounded reaction-kernel delta candidates.
- Stage145 does not apply deltas, mutate durable policy, learn model weights, write self-memory, call providers, change transport, start WeChat, or add a second loop; Stage135 topology can render a compact reaction-kernel shadow node.

Stage146: unified biomimetic replay and benchmark bundle
- Implemented read-only multi-turn replay export over stored Stage139-145 reply metadata with deterministic synthetic fixtures when runtime rows are unavailable.
- Exports `.html`, `.json`, and `.jsonl` artifacts that show packet timelines, A'/A'' gating, tool/memory observations, memory alignment, context slots, prediction error, reaction-kernel deltas, and stop reasons.
- Adds a deterministic benchmark bundle comparing single-call, simple RAG, fixed two-bubble, ungated multi-packet, and full RK-CSM stack conditions without provider calls, memory writes, tool execution, transport changes, policy mutation, or a second loop.

Stage147: replay-driven calibration
- Implemented deterministic shadow calibration over Stage146 replay rows.
- Evaluates whether Stage144 `skip`, `memory_first`, and `tool_first` recommendations are supported by later or fixture outcomes, and whether Stage145 reaction-kernel delta candidates have replay support or counterexamples.
- Reports shadow-only promotion candidates with support/counterexample counts and confidence while preserving the no-provider, no-tool, no-memory-write, no-policy-apply, no-WeChat, no-transport-widening boundary.

Stage148: reusable state memory and ReAct agent loop
- Implemented deterministic per-turn `stage148_react_state` over current input, recent event log, sidecar action state, capability context, and Stage139-145 observations.
- Separates raw chat/event logs from reusable state memory slots such as current user turn, recent correction, unresolved question, active task, action space, and packet-policy cue.
- Renders `Reusable State Memory` and `ReAct State` into the provider prompt and exposes a Stage135 `react_loop` topology node without adding provider calls, memory writes, tool execution, transport authority, WeChat starts, or a second loop.

Stage149: user directive kernel
- Implemented deterministic `stage149_user_directives` over current input, recent dialogue, existing sidecar evidence, and thread archive rows.
- Promotes user corrections such as "不要用 emoji" and "不要 role play" into packet-visible hard directives, applies final visible-output repair, and constrains Holo as a local subject runtime rather than a roleplay costume.
- Renders `User Directive State` into the provider prompt and exposes a Stage135 `user_directive_kernel` topology node without adding provider calls, memory writes, tool execution, transport authority, WeChat starts, private persona mutation, or a second loop.

Stage150: Codex-style context memory fabric
- Implemented deterministic `stage150_context_memory_fabric` over current input, Stage148 reusable state, Stage149 directives, recent dialogue, sidecar/debug evidence, and existing tool/memory/packet/context reports.
- Builds a structured working-context packet with instruction scope, current user goal, active task state, reusable slots, evidence ledger view, open loops, internal background compact, and forbidden visible claims.
- Renders `Engineering Context State` into the provider prompt and exposes a Stage135 `context_memory_fabric` topology node without adding provider calls, memory writes, tool execution, approval/sandbox policy, transport authority, WeChat starts, or a second loop.

Stage151: tool decision loop and live trace
- Implemented deterministic `stage151_tool_decision` over each turn with host time observation, action candidates, selected web actions, and normalized `web_observation_ledger` rows.
- Network actions are now explicit `web_search`, `open_page`, and `find_in_page` operations; `runtime.network_enabled=false` records `rejected_network_disabled` without fetching.
- CLI chat can show Codex-like `purpose`, `candidate`, `tool_call`, `observation`, `grounding`, and `final` trace lines without exposing hidden chain-of-thought, and Stage151 does not add provider calls, memory writes, tool authority, transport authority, approval/sandbox logic, WeChat starts, or a second loop.

Stage152: DeepSeek native tool loop
- Implemented DeepSeek thinking-mode native tool schemas for `time_observe`, `web_search`, `open_page`, `find_in_page`, and `memory_recall`.
- Live DeepSeek reply packets now preserve `reasoning_content` internally for API continuity, append host-executed `role=tool` results, and continue until no tool calls or the host stop controller stops.
- CLI trace now prefers Stage152 `purpose`, `candidate`, `tool`, `observation`, `evaluate`, `stop`, and `final` events when available; raw `reasoning_content` is never printed or archived as visible trace.
- Stage152 preserves host authority: web tools respect `runtime.network_enabled`, observations are recorded as ledgers, final web/current claims are grounded by Stage151, and no WeChat, memory-write, transport, approval, or sandbox boundary is widened.

Stage153: interactive agent CLI and event stream
- Implemented `stage153_agent_event_stream` and `stage153_interactive_cli_session` so CLI turns render auditable agent events: goal, context, candidates, tool calls, observations, grounding, cache, stop, and final speech.
- The `chat` command defaults to `holo_cli:default`, preserves the passed thread key and chat name, and supports `/trace`, `/json`, `/tools`, `/health`, `/memory`, `/compact`, `/clear`, and `/exit`.
- Stage153 redacts raw DeepSeek `reasoning_content`, does not start WeChat, does not execute new tools, does not add provider calls, and preserves Stage149-152 grounding constraints while adding a Stage135 `agent_event_stream` topology node.

Stage154: engineering action fabric
- Implemented workspace-scoped engineering actions for repo search, file read, patch application, guarded test commands, git status, and git diff.
- Every engineering action records an `engineering_action_ledger` row, and visible read/patch/test/diff claims are checked against the matching host evidence before delivery/archive.
- CLI can render `[eng:search]`, `[eng:read]`, `[eng:patch]`, `[eng:test]`, `[eng:diff]`, and `[eng:handoff]`; Stage154 rejects destructive commands by default, does not add provider calls, does not write memory, does not start WeChat, and adds a Stage135 `engineering_action_fabric` topology node.

Stage155: project state graph
- Implemented local SQLite-backed `project_state_nodes` and `project_state_edges` for project continuity across goals, tasks, decisions, open questions, artifacts, sources, assumptions, risks, results, and next actions.
- Stage150 working context now includes active project state, active tasks, open questions, latest decisions, next actions, and blocked items before provider generation.
- Reply/archive metadata, CLI `project-state` inspection, and Stage135 topology expose `project_state_graph` without provider calls, memory writes, tool execution, WeChat starts, or transport authority changes.

Stage156: context compiler and cache discipline
- Implemented a deterministic `context_compiler` surface that separates stable prefix, project instructions, tool schema, directives, dynamic turn state, observations, and final constraints.
- `reply_api.py` and `processors.py` now compile Stage156 before provider generation, render `Context Compiler State` into the prompt, update cache metrics from usage metadata, and propagate the report to reply JSON, outgoing/archive metadata, `ReplyPlan.debug`, CLI `/context` and `/cache`, and Stage135 topology.
- Keeps background compact internal, protects Stage149 directives from truncation, repairs visible compact leakage, and does not add provider calls, tool execution, memory writes, transport authority, WeChat starts, or live policy changes.

Stage157: Holo core bench
- Implemented HoloCoreBench as a deterministic `holo.stage157.core_bench.v1` reliability suite over recent recall, directive adherence, durable instructions, project-state recall, task continuation, web/time grounding, tool claim grounding, engineering patch/test claims, context compaction, CLI trace visibility, and stop-reason correctness.
- Writes `.html`, `.json`, and `.jsonl` artifacts through `python -m holo_host run-core-bench --output artifacts\stage157\holo_core_bench.html --dry-run`; `--fail-under` is the only mode that makes failures return nonzero.
- Scores pass rate, unsupported claim rate, directive violation rate, memory honesty, tool grounding, project continuity, context waste, cache hit ratio, and latency estimate without provider calls, tool execution, memory writes, WeChat starts, transport authority widening, or live policy changes.

Stage158: Agent Kernel v1
- Implemented scaffold-only domain modules for math research, physics research, market research, and ProjectH ops.
- Added `agent-kernel-readiness` to report whether the stable Agent Kernel v1 surfaces are available.
- Defines the boundary between stable core infrastructure and future domain expert modules without adding live domain work, provider calls, memory writes, tool execution, WeChat starts, or transport authority changes.

Stage159: Agent Kernel hardening
- Implemented public/private metadata splitting for Stage152 so raw DeepSeek `reasoning_content`, internal messages, raw decoded payloads, and hidden tool-loop packets do not reach public JSON, archive metadata, CLI `/json`, or event streams.
- Replaced Stage154 shell-based `test_run` execution with a strict argv allowlist, added canonical stop reason mapping, active readiness probes, offline live-smoke HoloCoreBench fixtures, and network health metadata.
- Keeps Stage159 safety/reliability-only: no provider calls, memory writes, WeChat starts, transport authority widening, live domain work, approval UI, or durable policy mutation.

Stage160R: depersonalized agent-loop FSM
- Added a host-owned `observe -> decide -> act_or_skip -> observe_result -> evaluate_stop -> final` FSM so mandatory actions must execute, fail, or be rejected before final speech.
- Added first-class intent frames and per-thread goal state so memory recall requests run host recall, follow-up turns inherit open goals, and `?` after a failed answer becomes a repair/follow-up path instead of social speculation.
- Depersonalized `holo_cli`/engineering/research/project prompt policy, rendered Stage153 CLI events from FSM steps, and exposed Stage160R in Stage150/156 context, reply/archive metadata, active thread state, and Stage135 topology without provider calls, memory writes, WeChat starts, or transport widening.

Stage161: model-first tool arbitration
- Added a structured model-visible tool action space covering direct answer, clarification, memory, time, web, workspace, engineering, git, project-state, and defer actions.
- Deterministic Stage151 routing now feeds weak `deterministic_hints`; the model proposes the next action, the host validates/executes/rejects, ledgers prove observations, and Stage160R FSM records `model_decide`.
- CLI event streams render `[action_space]` and `[model_decide]`, Stage135 topology exposes `model_tool_arbitration`, and final claims still require web/time, memory, or engineering ledgers without adding provider paths, memory writes, WeChat starts, or transport widening.

Stage162: search evidence controller
- Added bounded search-evidence planning and scoring so `web_search` evaluates official/docs/current source sufficiency instead of accepting any single result as enough.
- Stage151 web search now retries query variants through `run_search_evidence_controller`; Stage152 native web calls inherit the same controller because they execute through Stage151 host tools.
- Web observation rows carry `search_evidence`, Stage153 traces render evidence status/score, and Stage135 topology exposes search sufficiency metrics without adding provider paths, memory writes, WeChat starts, or transport widening.

Stage163: page evidence verifier
- Added page-body verification on top of Stage162 search result scoring so `web_search` can open candidate source URLs and verify that page text supports the requested query.
- Web observation rows now carry `page_evidence` with support status, opened count, selected URL, evidence score, supporting snippet, and page observations.
- Stage151/153 traces render page evidence status, Stage135 topology exposes `page_evidence_verifier`, and the stage preserves the no-provider-path, no-memory-write, no-WeChat-start, no-transport-widening boundary.

Stage164: search fallback and source synthesis
- Added host-side search provider fallback so `web_search` can try providers in order and record which provider produced sufficient Stage162 evidence.
- Added deterministic source synthesis over Stage163 page evidence, including supported/weak/conflicted/unsupported status, citations, confidence, and simple conflict flags.
- Stage151/153 traces render source synthesis status, Stage135 topology exposes `source_synthesis`, and the stage preserves the no-provider-model-path, no-memory-write, no-WeChat-start, no-transport-widening boundary.

Stage165: answer citation formatter
- Added deterministic answer-time citation formatting over Stage164 source synthesis.
- Stage151 grounded web answers now prefer synthesized page evidence, render numbered URLs and support snippets, include freshness notes, and use bounded language for weak, unsupported, or conflicted sources.
- Stage135 topology exposes `answer_citation_formatter` metrics while preserving the no-provider-model-path, no-memory-write, no-WeChat-start, no-transport-widening boundary.

Stage166: search quality evaluation
- Added deterministic search-quality evaluation over Stage151-165 for official docs, API docs, current information, financial filings, ambiguous entities, and failure cases.
- Reports source support, citation sufficiency, freshness, unsupported current/web claims, source conflicts, CSS/page chrome leakage, expected-term coverage, latency, and a raw-result baseline.
- Writes HTML/JSON/JSONL artifacts through `python -m holo_host run-search-quality-eval --output artifacts\stage166\stage166_search_quality.html --dry-run` without provider model calls, memory writes, WeChat starts, or transport widening.

Stage167: live search canary
- Added deterministic provider-comparison, source-freshness, quote-extraction, and ambiguous-entity canary checks over the Stage151-166 search evidence chain.
- Reports best provider, failed-provider count, source freshness markers, clean supporting quotes, ambiguity failures, and public artifact safety.
- Writes HTML/JSON/JSONL artifacts through `python -m holo_host run-live-search-canary --output artifacts\stage167\stage167_live_search_canary.html --dry-run` without provider model calls, memory writes, WeChat starts, or transport widening.

Stage168: source authority
- Added deterministic source-authority classification for financial filings, company IR, official docs, API docs, code repositories, package registries, news, and unclassified third-party summaries.
- `web_search` observations now carry `source_authority` after search evidence, page evidence, and source synthesis, so market-research and engineering tasks can reject the wrong kind of cited source.
- Writes HTML/JSON/JSONL artifacts through `python -m holo_host run-source-authority-audit --output artifacts\stage168\stage168_source_authority.html --dry-run` without provider model calls, memory writes, WeChat starts, or transport widening.

Stage169: market research pack
- Added deterministic filing-driven market-research packs with entity normalization, filing section extraction, 10-K checklist coverage, financial metric extraction, and metric consistency checks.
- Pack readiness is gated by Stage168 source authority, so financial/filing research cannot be treated as ready when only a third-party summary is available.
- Writes HTML/JSON/JSONL artifacts through `python -m holo_host run-market-research-pack --output artifacts\stage169\stage169_market_research_pack.html --dry-run` without provider model calls, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted `10 passed`, research stack `78 passed`, runtime `91 passed`, full regression `782 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage170: market research answer gate
- Added deterministic answer-time gating for market-research and financial-analysis replies.
- Financial metric, filing-section, and investment-judgment claims now require a ready Stage169 market-research pack before being stated as settled.
- Added `market_research_pack` to the model-first tool action space and exposed the `stage170_market_research_gate` in reply metadata and Stage135 topology.
- Verification on `2026-05-27`: targeted `11 passed`, market stack `47 passed`, runtime `92 passed`, full regression `794 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage171: market research pack action
- Added host execution for the `market_research_pack` action exposed by Stage170.
- DeepSeek-native tool calls can now request a read-only filing pack; the host records `market_research_pack_ledger`, attaches the Stage169 pack when built, and feeds Stage170 answer gating.
- Stage153 event streams and Stage135 topology expose the market-research pack action without provider model paths, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted `8 passed`, market stack `55 passed`, runtime `110 passed`, full regression `802 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage172: filing text retrieval
- Added host-side filing text retrieval for market-research packs.
- Stage171 can now consume existing Stage163 page evidence or open authoritative source URLs to extract filing text before building a Stage169 pack.
- Stage152, Stage153, reply metadata, archive metadata, and Stage135 topology expose `filing_text_retrieval` without provider model paths, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted `15 passed`, market stack `62 passed`, runtime `110 passed`, full regression `809 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage173: market research report
- Added deterministic filing-grounded analyst report generation over Stage169-172 evidence packs.
- Reports include source authority, filing coverage, section summaries, financial metrics, citations, limitations, unsupported-claim accounting, and weak web-only baseline comparison.
- Added `run-market-research-report` CLI artifacts and Stage135 `market_research_report` topology metrics without provider model paths, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted `8 passed`, market stack `54 passed`, runtime `92 passed`, full regression `817 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage174: market research report action
- Added a live `market_research_report` host action over Stage173 reports.
- DeepSeek native tool calls, the Stage161 action space, Stage160R FSM, Stage153 event streams, reply/archive metadata, and Stage135 topology now expose `market_research_report_ledger`.
- This connects market-research report generation to the actual agent loop without provider model paths outside processor fabric, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted integration `40 passed`, runtime `92 passed`, full regression `825 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage175: market research live smoke
- Added a deterministic live-smoke harness that runs a model-proposed `market_research_report` tool call through Stage152, Stage174, Stage160R, Stage153, and Stage135.
- The scorecard requires model-decision trace visibility, report ledgers, evidence-ready SEC-like citations, low unsupported-claim rate, known stop reasons, topology visibility, privacy, and persona-free output.
- Includes a weak third-party-source fixture that must fail rather than being promoted as a ready market-research report.
- Verification on `2026-05-27`: targeted Stage175 `8 passed`, market stack `24 passed`, runtime `92 passed`, full regression `833 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage176: market research domain benchmark
- Added an adversarial domain benchmark over Stage175 live-smoke results.
- The benchmark covers primary SEC-like evidence, third-party source pollution, missing filing sections, metric conflicts, period mismatch, and web-only/no-filing-text cases.
- Adds explicit domain gates for source authority, filing text presence, filing coverage, metric consistency, period alignment, unsupported claims, and agent trace validity, plus a naive web-overclaim baseline.
- Verification on `2026-05-27`: targeted Stage176 `10 passed`, market stack `44 passed`, runtime `92 passed`, full regression `843 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage177: market research remediation
- Added deterministic remediation planning over Stage176 domain failures.
- Failed market-research gates now map to concrete next actions: primary-source retry, filing text retrieval, metric-conflict report, period clarification/refetch, and explicit no-finalize messages for insufficient evidence.
- Added `run-market-research-remediation` CLI artifacts and Stage135 `market_research_remediation` topology metrics without provider calls, memory writes, WeChat starts, network requirements, or transport widening.
- Verification on `2026-05-27`: targeted Stage177 `10 passed`, market stack `28 passed`, runtime `92 passed`, full regression `853 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage178: evidence action remediation
- Added a domain-independent evidence/action remediation controller.
- Literature source gaps, math derivation gaps, GPU experiment failures, unsupported memory claims, missing tool ledgers, evidence conflicts, and scope mismatches now map to explicit next actions and success criteria.
- Added `run-evidence-action-remediation` CLI artifacts and Stage135 `evidence_action_remediation` topology metrics without provider calls, network fetches, tool execution, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted Stage178 `9 passed`, remediation stack `29 passed`, runtime `92 passed`, full regression `862 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage179: live remediation loop
- Connected Stage178 evidence-action remediation to the live agent-loop FSM.
- Remediation-required reports now produce `next_action_candidates`, `remediation_decide` / `remediation_plan` FSM steps, `[remediation]` event stream lines, bounded operator final text, and Stage135 `live_remediation_loop` topology metrics.
- Added `run-live-remediation-simulation` CLI artifacts without provider calls, network fetches, tool execution, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted Stage179 `7 passed`, remediation stack `26 passed`, runtime `92 passed`, full regression `869 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only. The final verification run included the `reply_api` live-path wiring.

Stage180: live remediation executor
- Added a controlled executor for Stage179 next-action candidates.
- `web_search`, `file_read`, and `memory_recall` remediation actions now run through existing host surfaces, produce ledgers, and re-enter the FSM as `remediation_execute` observations.
- Added `[remediation_exec]` CLI event rendering, `run-live-remediation-execution` artifacts, and Stage135 `live_remediation_executor` metrics without provider calls, write-action execution, memory writes, WeChat starts, or transport widening.

Stage181: live remediation stress
- Added adversarial stress simulation for the Stage178 -> Stage179 -> Stage180 remediation loop.
- Hardened Stage180 fallback and continuation semantics: fallback web success can recover a primary failure, skipped actions remain visible as `remaining_action_candidates`, multi-action budget exhaustion stops as `budget_exhausted`, and missing artifact paths stop as `needs_user_clarification`.
- Added `run-live-remediation-stress` artifacts and Stage135 `live_remediation_stress` metrics without provider calls, live-network requirements, write-action execution, memory writes, WeChat starts, or transport widening.
- Verification on `2026-05-27`: targeted Stage181/remediation stack `35 passed`, runtime `92 passed`, full regression `888 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage182: remediation continuation
- Added bounded multi-round remediation continuation over Stage179 action candidates using the Stage180 executor as the host action surface.
- The live reply path now uses Stage182 when remediation blocks finalization, preserving the aggregate Stage180 execution report while adding sufficiency scoring and explicit remaining-action state.
- Added `run-remediation-continuation` artifacts, `[remediation_continue]` event-stream visibility, and Stage135 `remediation_continuation` metrics without provider calls, memory writes, WeChat starts, transport widening, or live-network test requirements.
- Verification on `2026-05-27`: targeted Stage182 `8 passed`, remediation stack `43 passed`, runtime `92 passed`, full regression `896 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage183: agent capability gauntlet
- Added a Codex-style integrated capability gauntlet over Holo's base engineering/research kernel.
- The gauntlet evaluates engineering ledgers, market-research report ledgers, Stage182 remediation continuation, event-stream completeness, stop reasons, hidden-reasoning hygiene, persona-free output, and adversarial unsupported-claim detection.
- Added `run-agent-capability-gauntlet` artifacts and Stage135 `agent_capability_gauntlet` metrics without provider calls, memory writes, WeChat starts, transport widening, or live-network test requirements.
- Verification on `2026-05-27`: targeted Stage183 `8 passed`, integrated stack `33 passed`, runtime `92 passed`, full regression `904 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage184: real-use agent drill
- Added real-use drills that execute actual host actions in bounded temp workspaces and compare full-loop behavior against claim-only baselines.
- The engineering drill performs workspace search, file read, patch, pytest, git status, and git diff. The search drill drives Stage151 web observation/grounding with deterministic web providers, including network-disabled boundary handling. The market drill runs the Stage174 market-research report action and requires citations/report ledgers.
- Added `run-agent-real-use-drill` artifacts and Stage135 `real_use_drill` metrics without provider calls, memory writes, WeChat starts, transport widening, hidden reasoning exposure, or live-network test requirements.
- Verification on `2026-05-27`: targeted Stage184 `8 passed`, stack `53 passed`, runtime `92 passed`, full regression `912 passed`, public hygiene passed, and `git diff --check` had CRLF normalization warnings only.

Stage185: CLI introspection and search intent
- Added current-milestone state and public `[think]` deliberation summaries to the Stage153 CLI event stream.
- New turns no longer render `[stop] unknown`; legacy unknown stop metadata is mapped to a safe public stop reason.
- Hardened Chinese search/crawler/current-source intent recognition for Stage151 and `CapabilityBroker`, including planned `web_search` tool requests when eager network execution is disabled.
- Verification on `2026-05-27`: targeted Stage185 `6 passed`; neighbor `35 passed`; runtime `92 passed`; full suite `918 passed`; public hygiene and `git diff --check` passed.

Stage186: live crawler search
- Added a bounded query/open/evaluate crawler loop that records `crawler_ledger`, web observations, opened-page observations, source URLs, evidence sufficiency, and stop reasons.
- Added `run-live-crawler-search` artifacts for deterministic dry-run and optional live host web providers.
- Stage135 topology now exposes `live_crawler_search` node and metrics.
- Verification on `2026-05-27`: targeted Stage186 `8 passed`; neighbor `38 passed`; runtime `92 passed`; full suite `926 passed`; public hygiene and `git diff --check` passed.

Stage187: live chat crawler integration
- Wired Stage186 crawler search into `CapabilityBroker` eager web execution for agent channels.
- `holo_cli`, `engineering`, `research`, and `project` web-search turns now rebuild capability context with eager crawler execution when Stage151 selects `web_search`.
- Stage153 event stream renders `[crawl:query]`, `[crawl:search]`, `[crawl:open]`, `[crawl:evaluate]`, and `[crawl:stop]` from live crawler ledgers.
- Verification on `2026-05-27`: targeted Stage187 `2 passed`; neighbor `37 passed`; runtime `92 passed`; full suite `928 passed`; public hygiene passed; `git diff --check` had CRLF normalization warnings only.

Stage188: crawler evidence quality
- Hardened Stage163 opened-page evidence extraction so CSS-heavy documentation pages no longer leak `@layer`, selector blocks, CSS property fragments, custom-property `var(...)` fragments, or Astro-style selectors into source evidence.
- Stage151 web grounding and Stage186/187 crawler flows now receive cleaner readable page text and supporting snippets.
- Verification on `2026-05-27`: targeted Stage188 `2 passed`; neighbor `32 passed`; runtime `92 passed`; full suite `930 passed`; public hygiene passed; `git diff --check` had CRLF normalization warnings only.

Stage189: crawler source authority stop
- Integrated Stage168 source authority into the Stage186 crawler evaluation path.
- Financial/market-research crawler turns now continue past third-party pages when a primary filing or first-party disclosure is required, even if page text itself matches the query.
- Stage153 renders authority status in `[crawl:evaluate]` trace lines.
- Verification on `2026-05-27`: targeted Stage189 `4 passed`; neighbor `26 passed`; runtime `92 passed`; full suite `934 passed`; public hygiene passed; `git diff --check` had CRLF normalization warnings only.

## Next Program Arc (Planned)

This planned arc starts after Stage28. The durable execution sources of truth remain `.agent/PLANS.md` and `.agent/STAGE23_27_PROGRAM.md` until a Stage29+ program replaces them.

Provider/API compatibility breadth
- Planned. Future work should broaden API/provider compatibility through the processor fabric, not by adding raw hot-path provider calls.
- Visual-provider hardening should validate real configured `image_understand` lanes before Holo is restarted.

Online long-horizon canary
- Deferred until after a new explicit re-plan approves any live widening.
- Any future rollout must stay host-side, shadow-first, whitelist-bound, rate-limited, rollback-safe, replay-disciplined, and action-market-first.

Artifact/tool/outcome progress coupling
- Deferred. This older Stage25 placeholder was explicitly superseded by the dense continuity scheduler milestone and should not be silently folded into Stage28 or any post-Stage28 canary work.

Bounded subject programs
- Deferred. This is no longer the live Stage24 or Stage25 scope and should not be treated as implemented or active-planning default without an explicit re-plan.

## Parked Hypotheses
- broader multi-agent social world
- deeper imagination beyond current recall

## Deferred Experiments
- open-ended world modeling
- explicit multi-step planning
- richer subjective report layer

## Constitutional Constraints
- owner shutdown remains final
- no self-escalation around secrets, auth, or policy
- live repo code is not hot-edited by runtime state loops
- policy boundaries stay hard
- public repos never carry live memory/runtime state
- public repos never carry private subject-profile files; only `.example` templates are tracked
- no second brain layer
- no new unbounded always-on loop
- memory is the self
- processor is replaceable compute
- transport is eyes and hands
- action-market-first deliberation remains the decision path
