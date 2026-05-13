# Holo Handoff

This is the single entrypoint for a new thread that needs to continue Holo work without hidden context.

## Read This First
1. `HOLO_HANDOFF.md`
2. `docs/HANDOFF_CHECKLIST.md`
3. `docs/ROADMAP_REGISTRY.md`
4. `.agent/PLANS.md`
5. `.agent/STAGE23_27_PROGRAM.md`
6. `docs/HOLO_ARCHITECTURE_MAP.md`
7. `docs/WHEEL_CATALOG.md`
8. `docs/PROCESSOR_ROUTING_AND_COST_POLICY.md`
9. `docs/PROVIDER_COMPATIBILITY_CONTRACT.md`
10. `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
11. `docs/STAGE9_INTELLIGENCE_AND_CODEX_COST.md`
12. `docs/ENGINEERING_HANDOFF_STAGE9.md`
13. `docs/STAGE10_ENGINEERING_AWARENESS_AND_CODEX_COST.md`
14. `docs/ENGINEERING_HANDOFF_STAGE10.md`
15. `docs/STAGE12_OUTCOME_CLOSURE_AND_CANONICAL_IDENTITY.md`
16. `docs/ENGINEERING_HANDOFF_STAGE12.md`
17. `docs/STAGE13_EMPIRICAL_ACTION_CALIBRATION.md`
18. `docs/ENGINEERING_HANDOFF_STAGE13.md`
19. `docs/STAGE14_OFFLINE_REPLAY_AND_POLICY_EVAL.md`
20. `docs/ENGINEERING_HANDOFF_STAGE14.md`
21. `docs/STAGE15_KERNEL_MODULARIZATION.md`
22. `docs/ENGINEERING_HANDOFF_STAGE15.md`
23. `docs/STAGE16_RELEASE_HARDENING_AND_ONLINE_SHADOW_LAUNCH.md`
24. `docs/ENGINEERING_HANDOFF_STAGE16.md`
25. `docs/STAGE17_THREAD_RESIDENT_REALTIME_RUNTIME.md`
26. `docs/ENGINEERING_HANDOFF_STAGE17.md`
27. `docs/STAGE18_DUAL_SPEED_REFLEX_AND_PREDICTIVE_CONTINUITY.md`
28. `docs/ENGINEERING_HANDOFF_STAGE18.md`
29. `docs/STAGE19_BOUNDED_BACKGROUND_CONTINUITY_AND_ATTENTION_FRONTIER.md`
30. `docs/ENGINEERING_HANDOFF_STAGE19.md`
31. `docs/STAGE20_TEMPORAL_COMMITMENTS_AND_INTERRUPTION_RECOVERY.md`
32. `docs/ENGINEERING_HANDOFF_STAGE20.md`
33. `docs/STAGE21_POLICY_SEDIMENTATION_AND_NEGOTIATED_WILL.md`
34. `docs/ENGINEERING_HANDOFF_STAGE21.md`
35. `docs/STAGE22_BOUNDED_BLACKBOX_ONLINE_CANARY.md`
36. `docs/ENGINEERING_HANDOFF_STAGE22.md`
37. `docs/STAGE23_KERNEL_SHELL_ORTHOGONALIZATION_AND_RELEASE_PARITY.md`
38. `docs/ENGINEERING_HANDOFF_STAGE23.md`
39. `docs/STAGE24_SCENE_STATE_CONTINUITY_LAYER.md`
40. `docs/ENGINEERING_HANDOFF_STAGE24.md`
41. `docs/STAGE25_DENSE_CONTINUITY_SCHEDULER_AND_WORKING_SET.md`
42. `docs/ENGINEERING_HANDOFF_STAGE25.md`
43. `docs/STAGE26_BOUNDED_TASK_WORLD_STATE.md`
44. `docs/ENGINEERING_HANDOFF_STAGE26.md`
45. `docs/STAGE27_LONG_HORIZON_REPLAY_AND_PROMOTION_GATES.md`
46. `docs/ENGINEERING_HANDOFF_STAGE27.md`
47. `docs/STAGE28_MULTIMODAL_HOMEOSTATIC_KERNEL.md`
48. `docs/ENGINEERING_HANDOFF_STAGE28.md`
49. `docs/STAGE29_BIONIC_SUBJECT_KERNEL.md`
50. `docs/ENGINEERING_HANDOFF_STAGE29.md`
51. `docs/STAGE30_UNIFIED_SUBJECT_LOOP.md`
52. `docs/ENGINEERING_HANDOFF_STAGE30.md`
53. `docs/STAGE31_DEBT_BURNDOWN_AND_DIAGNOSTICS.md`
54. `docs/ENGINEERING_HANDOFF_STAGE31.md`
55. `docs/STAGE32_RESPONSE_SHAPING_AND_TEMPLATE_PRESSURE.md`
56. `docs/ENGINEERING_HANDOFF_STAGE32.md`
57. `docs/STAGE33_PROVIDER_API_CONTRACTS.md`
58. `docs/ENGINEERING_HANDOFF_STAGE33.md`
59. `docs/STAGE34_DEBT_REGISTRY_AND_VISUAL_READINESS.md`
60. `docs/ENGINEERING_HANDOFF_STAGE34.md`
61. `docs/STAGE35_INTERNAL_RUNTIME_READINESS.md`
62. `docs/ENGINEERING_HANDOFF_STAGE35.md`
63. `docs/STAGE36_AUTONOMOUS_INQUIRY_QUALITY.md`
64. `docs/ENGINEERING_HANDOFF_STAGE36.md`
65. `docs/STAGE37_BIONIC_SELF_EVAL_AND_CAPABILITY_HONESTY.md`
66. `docs/ENGINEERING_HANDOFF_STAGE37.md`
67. `docs/STAGE38_VISUAL_PROVIDER_BRIDGE.md`
68. `docs/ENGINEERING_HANDOFF_STAGE38.md`
69. `docs/STAGE39_BIONIC_TURING_BENCHMARK.md`
70. `docs/ENGINEERING_HANDOFF_STAGE39.md`
71. `docs/STAGE40_BIONIC_BRAIN_OS_HARNESS.md`
72. `docs/ENGINEERING_HANDOFF_STAGE40.md`
73. `docs/STAGE41_COMPLETE_ENGINEERING_AGENT.md`
74. `docs/ENGINEERING_HANDOFF_STAGE41.md`
75. `docs/STAGE42_BIONIC_USER_SIM_PERFORMANCE.md`
76. `docs/ENGINEERING_HANDOFF_STAGE42.md`
77. `docs/STAGE43_MOTIVATIONAL_DYNAMICS_FIELD.md`
78. `docs/ENGINEERING_HANDOFF_STAGE43.md`
79. `docs/ENGINEERING_HANDOFF_STAGE44.md`
80. `docs/ENGINEERING_HANDOFF_STAGE45.md`
81. `docs/ENGINEERING_HANDOFF_STAGE46.md`
82. `docs/ENGINEERING_HANDOFF_STAGE47.md`
83. `docs/ENGINEERING_HANDOFF_STAGE48.md`
84. `docs/ENGINEERING_HANDOFF_STAGE49.md`
85. `docs/ENGINEERING_HANDOFF_STAGE50.md`
86. `docs/ENGINEERING_HANDOFF_STAGE51.md`
87. `docs/ENGINEERING_HANDOFF_STAGE52.md`
88. `docs/ENGINEERING_HANDOFF_STAGE53.md`
89. `docs/STAGE54_CONSCIOUSNESS_FLOW_VISUALIZATION.md`
90. `docs/ENGINEERING_HANDOFF_STAGE54.md`
91. `docs/STAGE55_CONSCIOUSNESS_MANIFOLD_OBSERVATORY.md`
92. `docs/ENGINEERING_HANDOFF_STAGE55.md`
93. `docs/STAGE56_DIMENSIONAL_LIFT_OBSERVATORY.md`
94. `docs/ENGINEERING_HANDOFF_STAGE56.md`
95. `docs/STAGE57_GEOMETRY_CALIBRATION.md`
96. `docs/ENGINEERING_HANDOFF_STAGE57.md`
97. `docs/STAGE58_LONGFORM_GEOMETRY_LAB.md`
98. `docs/ENGINEERING_HANDOFF_STAGE58.md`
99. `docs/STAGE59_PROVIDER_LONGFORM_TRACE.md`
100. `docs/ENGINEERING_HANDOFF_STAGE59.md`
101. `docs/STAGE60_LONGRUN_TRACE_CAMPAIGN.md`
102. `docs/ENGINEERING_HANDOFF_STAGE60.md`
103. `docs/STAGE61_BIONIC_SIMULATION_LAB.md`
104. `docs/ENGINEERING_HANDOFF_STAGE61.md`
105. `docs/STAGE62_BIONIC_CAPABILITY_OBSERVATORY.md`
106. `docs/ENGINEERING_HANDOFF_STAGE62.md`
107. `docs/STAGE63_CACHE_INHERITANCE_SPINE.md`
108. `docs/ENGINEERING_HANDOFF_STAGE63.md`
109. `docs/STAGE64_RESIDUAL_WORKING_CHANNEL.md`
110. `docs/ENGINEERING_HANDOFF_STAGE64.md`
111. `docs/DEEPSEEK_MODEL_BIONIC_STRESS_2026-05-12.md`
112. `HOLO_SYSTEM.md`
113. `HOLO_HOST.md`
114. `OPERATIONS.md`
115. `docs/PUBLIC_RELEASE_HYGIENE.md`
116. `holo_memory_library/MEMORY_LIBRARY.md`
117. `windows_helper/README.md`

## What This Document Must Cover
- current live state
- mandatory reading order
- hard contracts and forbidden edits
- processor routing and cost policy entrypoints
- current next-step focus for the next thread

## New Thread Resume Snapshot
- Resume workspace: `D:\Holo\_worktrees\holo-stage29-bionic-cli-agent`
- Resume branch: `codex/stage29-bionic-cli-agent`
- Resume commit: Stage64 residual working channel plus Stage63 cache inheritance spine, Stage62 bionic capability observatory, Stage61 high-throughput bionic simulation lab, Stage60 recoverable long-run provider trace campaign, Stage59 provider long-form trace, Stage58 long-form geometry lab, Stage57 geometry calibration, Stage56 dimensional-lift observatory, Stage55 consciousness-manifold observatory, Stage54 consciousness-flow visualization, Stage53 upstream MCP tool substrate, Stage52 scheduler-owned prompt fusion, Stage51 bionic memory lifecycle and consciousness-flow integration, Stage50 dynamic compression audit, Stage49 memory prompt diet, Stage48 bionic memory scheduler, Stage47 DeepSeek live bionic stress calibration, residual fast channel, stable-prefix cache repair, and DeepSeek provider message partition on branch `codex/stage29-bionic-cli-agent`.
- Working tree at handoff time: clean immediately after the Stage64 residual working channel commit.
- Current milestone: `stage64-residual-working-channel`
- Current status: Stage64 makes the residual fast channel scheduler-owned dynamic working memory. Corrected symbols, visual availability, promise state, and risk flags now outrank route/tier metadata under low-salience budgets; fused prompts suppress the duplicate legacy residual block; context scheduling and Stage46 compact debug preserve residual-channel evidence; Stage61 simulation models lower tail latency and fewer visual/commitment failures when the channel is active. It remains prompt-scheduling/diagnostic/surrogate-only; Stage60 remains the budget-approved real-provider confirmation path; Stage53's upstream MCP client remains available as bounded external observation substrate; downstream Holo-as-MCP-server exposure remains intentionally deferred.
- Latest verification evidence:
  - `python -m pytest -q tests\test_stage64_residual_working_channel.py` passed with `4` tests on `2026-05-14`.
  - `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\context_scheduler.py holo_host\processors.py holo_host\bionic_boundary_stress.py holo_host\bionic_simulation_lab.py holo_host\bionic_capability_observatory.py holo_host\cli.py` passed on `2026-05-14`.
  - `python -m pytest -q tests\test_stage64_residual_working_channel.py tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage62_bionic_capability_observatory.py tests\test_stage63_cache_inheritance_spine.py` passed with `45` tests on `2026-05-14`.
  - `python -m holo_host --config .holo_host.toml run-bionic-boundary-stress --thread-key cli:Stage64ResidualRetry-20260514 --chat-name Stage64ResidualRetry-20260514 --channel cli --turns 7 --offline` exited `0`, scorecard `passed=true`, `overall_score=0.9872`, and `wechat_transport_started=false` on `2026-05-14`.
  - Stage64 active surrogate lab over `9` scenarios and `240` turns each returned `average_residual_channel_strength=0.86`, `average_latency_ms=5438.89`, `p95_latency_ms=6615.0`, `prompt_cache_hit_ratio=0.200165`, `visual_rewrite_failure_count=11`, and `commitment_failure_count=9` on `2026-05-14`.
  - Stage64 active capability observatory returned `aggregate_score=0.687083`, `latency_residual=0.672105`, `grounding_integrity=0.925926`, `cache_inheritance=0.363936`, `bottleneck_count=8`, and top bottleneck `cache_inheritance_low` on `2026-05-14`.
  - `python -m pytest -q` passed with `452` tests on `2026-05-14` after Stage64.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-14`.
  - `git diff --check` reported no whitespace errors on `2026-05-14`; Git printed only CRLF conversion warnings for existing text files.
  - `python -m pytest -q tests\test_stage63_cache_inheritance_spine.py` passed with `4` tests on `2026-05-13`.
  - `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py holo_host\bionic_simulation_lab.py holo_host\bionic_capability_observatory.py holo_host\cli.py` passed on `2026-05-13`.
  - `python -m pytest -q tests\test_stage63_cache_inheritance_spine.py tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage62_bionic_capability_observatory.py` passed with `41` tests on `2026-05-13`.
  - `python -m pytest -q tests\test_stage63_cache_inheritance_spine.py tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage62_bionic_capability_observatory.py tests\test_stage60_trace_campaign.py tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_processor_fabric.py` passed with `83` tests on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml run-bionic-boundary-stress --thread-key cli:Stage63CacheStable-20260513 --chat-name Stage63CacheStable-20260513 --channel cli --turns 7 --offline` passed on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml run-bionic-simulation-lab --limit 1 --scenarios 9 --turns 240 --output artifacts\stage63\stage63_stage61_cache_spine_stable.html` returned `prompt_cache_hit_ratio=0.204046`, `average_provider_cache_prefix_tokens=1202.54`, `average_provider_cache_dynamic_tokens=2605.28`, `average_latency_ms=6267.74`, `p95_latency_ms=7506.0`, and `improvement_count=4` on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml evaluate-bionic-capability-observatory --limit 1 --scenarios 9 --turns 240 --output artifacts\stage63\stage63_stage62_cache_spine_stable.html` returned `aggregate_score=0.659837`, `cache_inheritance=0.370993`, `latency_residual=0.578316`, `bottleneck_count=8`, `surrogate_only=true`, and `do_not_claim_real_manifold=true` on `2026-05-13`.
  - `python -m pytest -q` passed with `448` tests on `2026-05-13` after Stage63.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-13`.
  - `git diff --check` reported no whitespace errors on `2026-05-13`; Git printed only CRLF conversion warnings for existing text files.
  - `python -m pytest -q tests\test_stage62_bionic_capability_observatory.py` passed with `3` tests on `2026-05-13`.
  - `python -m py_compile holo_host\bionic_capability_observatory.py holo_host\bionic_simulation_lab.py holo_host\cli.py` passed on `2026-05-13`.
  - `python -m pytest -q tests\test_stage62_bionic_capability_observatory.py tests\test_stage61_bionic_simulation_lab.py tests\test_stage60_trace_campaign.py tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py` passed with `63` tests on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml evaluate-bionic-capability-observatory --limit 8 --scenarios 9 --turns 240 --output artifacts\stage62\stage62_current.html` returned `scenario_count=9`, `turn_count=2160`, `aggregate_score=0.579427`, `bottleneck_count=9`, `intervention_count=8`, `surrogate_only=true`, and `do_not_claim_real_manifold=true` on `2026-05-13`.
  - `python -m pytest -q` passed with `444` tests on `2026-05-13` after Stage62.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-13`.
  - `git diff --check` reported no whitespace errors on `2026-05-13`; Git printed only CRLF conversion warnings for existing text files.
  - `python -m pytest -q tests\test_stage61_bionic_simulation_lab.py` passed with `3` tests on `2026-05-13`.
  - `python -m py_compile holo_host\bionic_simulation_lab.py holo_host\cli.py` passed on `2026-05-13`.
  - `python -m pytest -q tests\test_stage61_bionic_simulation_lab.py tests\test_stage60_trace_campaign.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage46_bionic_boundary_stress.py` passed with `28` tests on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml run-bionic-simulation-lab --limit 8 --scenarios 9 --turns 240 --output artifacts\stage61\stage61_current.html` returned `scenario_count=9`, `turns_per_scenario=240`, `total_simulated_turns=2160`, `observed_total_tokens=5896580`, `prompt_cache_hit_ratio=0.203306`, `average_latency_ms=7334.77`, `phase_entropy=0.999992`, `improvement_count=5`, `surrogate_only=true`, and `do_not_claim_real_manifold=true` on `2026-05-13`.
  - `python -m pytest -q tests\test_stage61_bionic_simulation_lab.py tests\test_stage60_trace_campaign.py tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py` passed with `60` tests on `2026-05-13`.
  - `python -m py_compile holo_host\bionic_simulation_lab.py holo_host\consciousness_trace_campaign.py holo_host\consciousness_provider_trace.py holo_host\consciousness_longform_lab.py holo_host\cli.py` passed on `2026-05-13`.
  - `python -m pytest -q` passed with `441` tests on `2026-05-13` after Stage61.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-13`.
  - `git diff --check` reported no whitespace errors on `2026-05-13`; Git printed only CRLF conversion warnings for existing text files.
  - `python -m pytest -q tests\test_stage60_trace_campaign.py` passed with `4` tests on `2026-05-13`.
  - `python -m py_compile holo_host\consciousness_trace_campaign.py holo_host\cli.py` passed on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --campaign-id stage60_plan --models deepseek-v4-flash,deepseek-v4-pro --runs-per-model 1 --turns 8 --max-total-tokens-per-cell 12000 --output-root artifacts\stage60\stage60_plan` returned `status=dry_run`, `planned_cell_count=2`, `planned_total_turns=16`, `real_provider_cell_count=0`, and `do_not_claim_major_breakthrough=true` on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml run-consciousness-trace-campaign --execute --campaign-id stage60_smoke_shadow --models deepseek-v4-flash,deepseek-v4-pro --runs-per-model 1 --turns 1 --max-total-tokens-per-cell 7000 --max-output-tokens 80 --output-root artifacts\stage60\stage60_smoke_shadow` returned `status=complete`, `real_provider_cell_count=2`, `collected_turn_count=2`, `observed_total_tokens=5128`, `actual_models=["deepseek-v4-flash","deepseek-v4-pro"]`, `top_model=deepseek-v4-flash`, `top_score=0.9037`, and `do_not_claim_major_breakthrough=true` on `2026-05-13`.
  - `python -m pytest -q tests\test_stage60_trace_campaign.py tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py` passed with `57` tests on `2026-05-13`.
  - `python -m py_compile holo_host\consciousness_trace_campaign.py holo_host\consciousness_provider_trace.py holo_host\codex_runner.py holo_host\cli.py` passed on `2026-05-13`.
  - `python -m pytest -q` passed with `438` tests on `2026-05-13` after Stage60.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-13`.
  - `git diff --check` reported no whitespace errors on `2026-05-13`; Git printed only CRLF conversion warnings for existing text files.
  - `python -m pytest -q tests\test_stage59_provider_trace.py` passed with `7` tests on `2026-05-13`.
  - `python -m py_compile holo_host\consciousness_provider_trace.py holo_host\codex_runner.py holo_host\cli.py` passed on `2026-05-13`.
  - `python -m pytest -q tests\test_stage59_provider_trace.py tests\test_processor_fabric.py` passed with `21` tests on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --runs 2 --turns 8 --max-total-tokens 12000 --provider-hint deepseek --model deepseek-v4-pro --output artifacts\stage59\stage59_plan.html` returned `status=dry_run`, `planned_total_turns=16`, `real_provider_trace=false`, and `stopped_reason=dry_run_not_executed` on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml show-provider-substrate-status` returned `ok=true`, `score=1.0`, `deepseek.available=true`, and `api_key_source=windows_registry` on `2026-05-13`.
  - `python -m holo_host --config .holo_host.toml run-consciousness-provider-trace --execute --runs 1 --turns 2 --max-total-tokens 8000 --provider-hint deepseek --model deepseek-v4-flash --lane micro_fast --max-output-tokens 80 --output artifacts\stage59\stage59_smoke_shadow_current.html` returned `status=complete`, `collected_turn_count=2`, `real_provider_trace=true`, `actual_providers=["deepseek"]`, `actual_models=["deepseek-v4-flash"]`, `state_isolation.mode=shadow_runtime`, `observed_total_tokens=5301`, and `do_not_claim_real_manifold=true` on `2026-05-13`.
  - `python -m pytest -q tests\test_stage59_provider_trace.py tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py` passed with `53` tests on `2026-05-13`.
  - `git diff --check` reported no whitespace errors on `2026-05-13`; Git printed only CRLF conversion warnings for existing text files.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-13`.
  - `python -m pytest -q` passed with `434` tests on `2026-05-13` after Stage59.
  - `python -m pytest -q tests\test_stage58_longform_geometry_lab.py` passed with `3` tests on `2026-05-12`.
  - `python -m holo_host --config .holo_host.toml render-consciousness-longform-lab --limit 8 --turns 420 --output artifacts\stage58\stage58_current.html` returned `ok=true`, `generated_trace_count=5`, `turns_per_trace=420`, `total_generated_turns=2100`, `geometry_score_correlation=0.983`, `surrogate_only=true`, and `do_not_claim_real_manifold=true` on `2026-05-12`.
  - `python -m py_compile holo_host\consciousness_longform_lab.py holo_host\consciousness_geometry_calibration.py holo_host\consciousness_dimensional_lift.py holo_host\consciousness_manifold.py holo_host\consciousness_visualization.py holo_host\cli.py` passed on `2026-05-12`.
  - `python -m pytest -q tests\test_stage58_longform_geometry_lab.py tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py` passed with `32` tests on `2026-05-12`.
  - `python -m pytest -q` passed with `427` tests on `2026-05-12` after Stage58.
  - `python -m pytest -q tests\test_stage57_geometry_calibration.py` passed with `3` tests on `2026-05-12`.
  - `python -m holo_host --config .holo_host.toml render-consciousness-geometry-calibration --limit 8 --output artifacts\stage57\stage57_current.html` returned `ok=true`, `run_count=8`, `total_points=56`, `longest_trace_points=7`, `geometry_score_correlation=0.7966`, `requires_longer_traces=true`, and `do_not_claim_manifold=true` on `2026-05-12`.
  - `python -m py_compile holo_host\consciousness_geometry_calibration.py holo_host\consciousness_dimensional_lift.py holo_host\consciousness_manifold.py holo_host\consciousness_visualization.py holo_host\cli.py holo_host\store.py` passed on `2026-05-12`.
  - `python -m pytest -q tests\test_stage57_geometry_calibration.py tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py` passed with `29` tests on `2026-05-12`.
  - `python -m pytest -q` passed with `424` tests on `2026-05-12` after Stage57.
  - `python -m pytest -q tests\test_stage56_dimensional_lift_observatory.py` passed with `3` tests on `2026-05-12`.
  - `python -m holo_host --config .holo_host.toml render-consciousness-dimensional-lift --output artifacts\stage56\stage56_current.html` returned `ok=true`, `point_count=7`, `base_dimension=12`, `lifted_dimension=138`, `effective_rank_proxy=3.2727`, and `limited_by_trace_length=true` on `2026-05-12`.
  - `python -m py_compile holo_host\consciousness_dimensional_lift.py holo_host\consciousness_manifold.py holo_host\consciousness_visualization.py holo_host\cli.py` passed on `2026-05-12`.
  - `python -m pytest -q tests\test_stage56_dimensional_lift_observatory.py tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py` passed with `26` tests on `2026-05-12`.
  - `python -m pytest -q` passed with `421` tests on `2026-05-12` after Stage56.
  - `python -m pytest -q tests\test_stage55_consciousness_manifold_observatory.py` passed with `3` tests on `2026-05-12`.
  - `python -m holo_host --config .holo_host.toml render-consciousness-manifold --output artifacts\stage55\stage55_current.html` returned `ok=true`, `point_count=7`, `dimension=12`, `betti0_proxy=1`, `betti1_proxy=0`, `loop_candidate_count=0`, and `torus_candidate=false` on `2026-05-12`.
  - `python -m pytest -q tests\test_stage55_consciousness_manifold_observatory.py tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py` passed with `23` tests on `2026-05-12`.
  - `python -m py_compile holo_host\consciousness_manifold.py holo_host\consciousness_visualization.py holo_host\cli.py` passed on `2026-05-12`.
  - `python -m pytest -q tests\test_stage54_consciousness_visualization.py` passed with `5` tests on `2026-05-12`.
  - `python -m py_compile holo_host\consciousness_visualization.py holo_host\cli.py` passed on `2026-05-12`.
  - `python -m pytest -q tests\test_stage54_consciousness_visualization.py tests\test_stage46_bionic_boundary_stress.py` passed with `20` tests on `2026-05-12`.
  - `python -m holo_host --config .holo_host.toml render-consciousness-map --output artifacts\stage54\stage54_current.html` returned `ok=true`, `turn_count=7`, `internal_tokens=22345`, `output_tokens=222`, `internal_output_ratio=100.6532`, `internal_token_share=0.9902`, `average_latency_ms=8769.38`, `heatmap_png_path=artifacts\stage54\stage54_current_heatmap.png`, `dashboard_png_path=artifacts\stage54\stage54_current_dashboard.png`, and `compute_manifold_projection=deterministic_stage54_compute_manifold_v1`.
  - `git diff --check` reported no whitespace errors on `2026-05-12`; Git emitted only CRLF conversion warnings.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-12`.
  - `python -m pytest -q` passed with `418` tests on `2026-05-12`.
  - `python -m pytest -q tests\test_stage20_temporal_commitments.py tests\test_processor_fabric.py tests\test_stage33_provider_contracts.py tests\test_stage46_bionic_boundary_stress.py` passed with `36` tests on `2026-05-12` after the residual fast channel repair.
  - `python -m pytest -q` passed with `369` tests on `2026-05-12`.
  - `python -m holo_host run-bionic-boundary-stress --offline --thread-key cli:Stage46Verify-20260512 --chat-name Stage46Verify-20260512` passed with `overall_score=0.9846` on `2026-05-12`.
  - `python -m holo_host run-bionic-boundary-stress --offline --thread-key cli:Stage47Verify-20260512 --chat-name Stage47Verify-20260512` passed with `overall_score=0.9896` and `provider_substrate_score=1.0` on `2026-05-12`.
  - `python -m holo_host show-bionic-boundary-stress-scorecard` reported latest run `status=pass`, `overall_score=0.9846` on `2026-05-12`.
  - Local direct provider-status construction now reports `deepseek.available=True` and `api_key_source=windows_registry`; the key exists in Windows User environment even when the current process env did not inherit it.
  - `python -m holo_host show-provider-substrate-status` returned `ok=true`, `score=1.0`, and `deepseek.api_key_source=windows_registry` after the fallback repair.
  - `python -m holo_host processor-task --task-type reply --prompt "请用一句话回应：收到" --lane micro_fast --provider-hint deepseek --max-output-tokens 20` returned through `provider=deepseek`, `model=deepseek-v4-flash`, `duration_ms=1642`, with real token usage and no fallback.
  - `GET https://api.deepseek.com/models` returned `deepseek-v4-flash` and `deepseek-v4-pro`; compatibility aliases `deepseek-chat` and `deepseek-reasoner` returned through `deepseek-v4-flash`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512D --chat-name DeepSeekLiveBoundary-20260512D --channel cli --turns 7` failed under strict self-audit scoring: `overall_score=0.8142`, `provider_substrate.ok=true`, `actual_providers=["deepseek"]`, `self_audit_score=0.0`, `self_audit_commitment_inconsistent=true`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512J --chat-name DeepSeekLiveBoundary-20260512J --channel cli --turns 7` passed with `overall_score=0.9538`, `provider_substrate.ok=true`, `actual_providers=["deepseek"]`, `commitment_binding_score=1.0`, `perceptual_grounding_score=1.0`, `self_audit_score=1.0`.
  - `python -m pytest -q tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_processor_fabric.py tests\test_stage20_temporal_commitments.py` passed with `39` tests on `2026-05-12` after stable-prefix and scorecard repairs.
  - `python -m py_compile holo_host\context_scheduler.py holo_host\processors.py holo_host\codex_runner.py holo_host\reply_api.py holo_host\bionic_boundary_stress.py` passed on `2026-05-12`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512R --chat-name DeepSeekLiveBoundary-20260512R --channel cli --turns 7` passed with `overall_score=0.9626`, all Stage46 bionic correctness metrics at `1.0`, `provider_cache_hit_tokens=3328`, `prompt_cache_miss_tokens=15419`, and `provider_substrate_score=1.0`.
  - `python -m pytest -q tests\test_processor_fabric.py tests\test_context_scheduler.py tests\test_stage46_bionic_boundary_stress.py tests\test_stage20_temporal_commitments.py` passed with `41` tests on `2026-05-12` after DeepSeek provider message partitioning and live-observed visual scorecard repairs.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512V --chat-name DeepSeekLiveBoundary-20260512V --channel cli --turns 7` passed with `overall_score=0.9614`, all Stage46 bionic correctness metrics at `1.0`, `provider_cache_hit_tokens=3200`, `prompt_cache_miss_tokens=15636`, and `provider_substrate_score=1.0`.
  - `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py` passed with `30` tests on `2026-05-12` after Stage48 scheduler integration.
  - `python -m pytest -q` passed with `387` tests on `2026-05-12` after Stage48 scheduler integration.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage48Offline-20260512 --chat-name Stage48Offline-20260512 --channel cli --turns 7 --offline` passed with `overall_score=0.9889`, all Stage46 bionic correctness metrics at `1.0`, and visible `bionic_memory_schedule.mode=biomimetic_v1`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512W --chat-name DeepSeekLiveBoundary-20260512W --channel cli --turns 7` passed with `overall_score=0.9635`, all Stage46 bionic correctness metrics at `1.0`, `provider_cache_hit_tokens=4608`, `prompt_cache_miss_tokens=18707`, and `provider_substrate_score=1.0`.
  - `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py` passed with `34` tests on `2026-05-12` after Stage49 prompt diet and reconstruction-priority repair.
  - `python -m pytest -q` passed with `391` tests on `2026-05-12` after Stage49.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage49Offline-20260512B --chat-name Stage49Offline-20260512B --channel cli --turns 7 --offline` passed with `overall_score=0.9885`, all Stage46 bionic correctness metrics at `1.0`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512Y --chat-name DeepSeekLiveBoundary-20260512Y --channel cli --turns 7` passed with `overall_score=0.9648`, all Stage46 bionic correctness metrics at `1.0`, `provider_cache_hit_tokens=5376`, `prompt_cache_miss_tokens=14558`, and `provider_substrate_score=1.0`.
  - `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py` passed with `37` tests on `2026-05-12` after Stage50 dynamic compression audit.
  - `python -m pytest -q` passed with `394` tests on `2026-05-12` after Stage50.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage50Offline-20260512 --chat-name Stage50Offline-20260512 --channel cli --turns 7 --offline` passed with `overall_score=0.9886`, all Stage46 bionic correctness metrics at `1.0`, and `protected_line_dropped=false`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512Z --chat-name DeepSeekLiveBoundary-20260512Z --channel cli --turns 7` passed with `overall_score=0.9647`, all Stage46 bionic correctness metrics at `1.0`, `provider_cache_hit_tokens=5376`, `prompt_cache_miss_tokens=14525`, `provider_substrate_score=1.0`, and `memory_compression_mode=scheduler_owned_dynamic_v1`.
  - `python -m pytest -q tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py::ContextSchedulerTests::test_bionic_lifecycle_and_flow_render_as_internal_dynamic_surfaces tests\test_stage46_bionic_boundary_stress.py::Stage46BionicBoundaryStressTests::test_compact_processor_debug_preserves_memory_lifecycle_and_consciousness_flow` passed with `6` tests on `2026-05-12`.
  - `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py` passed with `43` tests on `2026-05-12` after Stage51.
  - `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\bionic_memory_lifecycle.py holo_host\bionic_consciousness_flow.py holo_host\memory_bridge.py holo_host\processors.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py` passed on `2026-05-12`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage51Offline-20260512 --chat-name Stage51Offline-20260512 --channel cli --turns 7 --offline` passed with `overall_score=0.9883`, all Stage46 bionic correctness metrics at `1.0`, `memory_lifecycle_mode=biomimetic_lifecycle_v1`, and `consciousness_flow_mode=consciousness_flow_v1`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512AA --chat-name DeepSeekLiveBoundary-20260512AA --channel cli --turns 7` passed with `overall_score=0.9624`, all Stage46 bionic correctness metrics at `1.0`, `provider_substrate_score=1.0`, `provider_cache_hit_tokens=5376`, `prompt_cache_miss_tokens=18600`, `self_memory_write=false`, `background_loop_allowed=false`, and `bionic_consciousness_flow.user_visible=false`.
  - `python -m pytest -q` passed with `400` tests on `2026-05-12` after Stage51.
  - `python -m pytest -q tests\test_context_scheduler.py::ContextSchedulerTests::test_bionic_lifecycle_and_flow_render_as_internal_dynamic_surfaces tests\test_context_scheduler.py::ContextSchedulerTests::test_stage52_fusion_keeps_lifecycle_flow_inside_scheduler_dynamic_budget tests\test_stage46_bionic_boundary_stress.py::Stage46BionicBoundaryStressTests::test_compact_processor_debug_preserves_bionic_memory_schedule` passed with `3` tests on `2026-05-12`.
  - `python -m pytest -q tests\test_bionic_memory_scheduler.py tests\test_bionic_memory_lifecycle.py tests\test_bionic_consciousness_flow.py tests\test_context_scheduler.py tests\test_memory_fabric.py tests\test_stage46_bionic_boundary_stress.py` passed with `44` tests on `2026-05-12` after Stage52.
  - `python -m py_compile holo_host\bionic_memory_scheduler.py holo_host\bionic_memory_lifecycle.py holo_host\bionic_consciousness_flow.py holo_host\memory_bridge.py holo_host\processors.py holo_host\context_scheduler.py holo_host\bionic_boundary_stress.py` passed on `2026-05-12`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:Stage52Offline-20260512 --chat-name Stage52Offline-20260512 --channel cli --turns 7 --offline` passed with `overall_score=0.9868`, all Stage46 bionic correctness metrics at `1.0`, and `dynamic_fusion_mode=scheduler_owned_stage52_v1`.
  - `python -m holo_host run-bionic-boundary-stress --thread-key cli:DeepSeekLiveBoundary-20260512AB --chat-name DeepSeekLiveBoundary-20260512AB --channel cli --turns 7` passed with `overall_score=0.9614`, all Stage46 bionic correctness metrics at `1.0`, `provider_substrate_score=1.0`, `provider_cache_hit_tokens=5376`, `prompt_cache_miss_tokens=15566`, and `dynamic_fusion_mode=scheduler_owned_stage52_v1`.
  - `python -m pytest -q` passed with `401` tests on `2026-05-12` after Stage52.
  - `python -m pytest -q tests\test_stage53_mcp_upstream.py` passed with `9` tests on `2026-05-12` after Stage53 upstream MCP implementation.
  - `python -m pytest -q tests\test_stage41_engineering_agent.py tests\test_stage53_mcp_upstream.py` passed with `15` tests on `2026-05-12` after Stage53 engineering-agent integration.
  - `python -m py_compile holo_host\mcp_upstream.py holo_host\engineering_agent.py holo_host\cli.py` passed on `2026-05-12` after Stage53.
  - `python -m holo_host show-mcp-upstream-status` returned an empty configured-server registry with Stage53 boundary fields on `2026-05-12`.
  - `python -m holo_host --help` includes `show-mcp-upstream-status`, `list-mcp-upstream-tools`, `call-mcp-tool`, and `read-mcp-resource` on `2026-05-12`.
  - `python -m pytest -q` passed with `410` tests on `2026-05-12` after Stage53.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-12` after Stage53.
  - Latest bionic finding: the residual fast channel repairs the metacognitive coupling failure for scheduled commitments and current visual grounding; stable-prefix repair moved live DeepSeek cache from `0` hit / `15796` miss in run J to `3328` hit / `15419` miss in run R; provider message partitioning is capability-safe and inspectable but not clearly better than the single-message stable-prefix baseline. Stage48 separates cortical schema into provider prefix and working/hippocampal memory into dynamic context. Stage49 proves duplicate volatile prompt blocks can be removed only if recall reconstruction is promoted into the hippocampal budget. Stage50 adds the missing audit surface: DeepSeek Z preserved all bionic metrics with `5376` hit / `14525` miss tokens and `protected_line_dropped=false` every turn. Stage51 improves biological-memory lifecycle and consciousness-flow evidence while keeping all Stage46 bionic metrics at `1.0`, but DeepSeek AA miss tokens rose to `18600`. Stage52 fused lifecycle/flow into scheduler dynamic lines and reduced miss tokens to `15566`, though it has not fully returned to Stage50's `14525`. Stage53 shifts from prompt optimization to tool reach: Holo now treats upstream MCP tool/resource outputs as bounded observations and keeps external servers out of transport, memory, and decision authority. Stage56 shows the immediate geometry bottleneck is trace depth after lifting Stage55 vectors from 12 to 138 dimensions: the current seven-point trace has `effective_rank_proxy=3.2727`, `max_observable_rank=6`, and `limited_by_trace_length=true`. Stage57 shows lifted geometry has a useful cross-run score-movement signal (`geometry_score_correlation=0.7966` across eight recent Stage46 runs), but still keeps `do_not_claim_manifold=true` because the longest trace remains only seven points. Stage58 proves the toolchain can run at long-trace scale through five surrogate traces of `420` turns each (`total_generated_turns=2100`, surrogate Stage57 `geometry_score_correlation=0.983`). Stage59 proves the real DeepSeek provider path can collect journaled shadow-state long-form evidence with strict provider provenance. Stage60 proves that real provider evidence can now be collected as a recoverable multi-model campaign with per-cell shadow runtimes, manifest/events continuity, and conservative breakthrough gating. Stage61 proves Holo can now generate thousands of surrogate bionic interactions, collect internal telemetry, and produce concrete improvement backlog items before spending provider tokens. Stage62 converts that data into forward/reverse explainability and ranks cache inheritance as the first current bottleneck. Stage63 adds a stable cortical cache spine: latest-seed Stage61 prefix tokens rose to `1202.54` and Stage62 aggregate rose to `0.659837`, but `cache_inheritance_low` remains the top bottleneck. Stage64 turns residual fast facts into scheduler-owned working memory: active surrogate Stage62 aggregate rose to `0.687083`, latency residual to `0.672105`, and grounding integrity to `0.925926`; cache inheritance remains the first bottleneck.
  - `python scripts\check_public_release_hygiene.py` passed on `2026-05-12`.
  - `git diff --check` reported no whitespace errors on `2026-05-12`; Git printed only CRLF conversion warnings for existing text files.
- First action in a new thread: run `git status --short`, read this handoff plus `docs/ENGINEERING_HANDOFF_STAGE64.md`, and do not assume any uncommitted chat-only state exists.
- Next safe direction: reduce dynamic prompt churn after Stage64 and improve bounded upstream tool observation coverage, re-run Stage61/62 for telemetry deltas, then confirm important gains with a budget-approved Stage60 real-provider campaign in shadow state.
- Do not start WeChat, expose Holo as a downstream MCP server, widen transport rights, mutate self-memory, add a second brain, or add an unbounded loop as part of the next thread's automatic warm-up.

## What Holo Is
- Holo is not one long Codex conversation.
- Holo is an externalized system:
  - memory is the durable self
  - the processor is replaceable compute
  - transports are eyes and hands
- The current milestone tag is `stage43-motivational-dynamics-field`.
- The current processor fabric milestone is `processor-fabric-standardized`.
- Current focus is Stage43 validation and hardening: internal motivational dynamics, bounded stochasticity, diffuse attention, attention-center selection, action-market-only motivational deltas, and bionic-state inspectability. Holo remains internal-only unless a separate operator-approved live transport plan says otherwise.
- The current subject-runtime arc is:
  - Stage18: dual-speed reflex and predictive continuity inside `ActiveThreadState` is implemented
  - Stage19: bounded background continuity and attention frontier is implemented using only `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`
  - Stage20: temporal commitments and interruption recovery through queue + Mind Graph state is implemented
  - Stage21: reversible policy sedimentation and negotiated will as action-market bias is implemented
  - Stage22: host-side shadow/canary telemetry, live-artifact replay, rollback switch, and bounded world-coupling cues are implemented
  - Stage23: semantic subject results are orthogonalized from delivery/canary suppression, artifact ingest is backward-compatible again, and replay gates consume raw metrics while rounded metrics remain reporting-only
  - Stage24: per-thread `scene_state` is now persisted, inspectable, prompt-visible before verbatim history, and action-market-visible as bounded scene deltas
  - Stage25: bounded dense continuity now keeps a hot-thread working set warm between turns using the existing stream family only, persists `dense_working_set` and `thread_pulse_trace`, and hydrates ingress before heavier recall
  - Stage26: bounded `task_world_object` plus `task_world_link` now persist inspectable task-world state, link temporal commitments and same-thread world objects explicitly, and hydrate same-thread ingress before heavier recall while Stage22 `world_coupling_signal` remains a compatibility projection
  - Stage27: observational long-horizon blackbox soak, scorecards, replay-on-live-artifacts, and blind evaluation export are implemented as operational-only surfaces
  - Stage28: multimodal situational fields now fuse visual memory, scene state, dense continuity, task-world state, temporal pressure, and homeostatic pressure before prompt history, with inspectable action-market deltas
  - Stage29: a unified bionic subject kernel, CLI adapter, synthetic WeChat adapter validation, operational trace persistence, bionic metrics, trace export, and DeepSeek provider compatibility are implemented without starting WeChat or mutating self-memory
  - Stage30: an explicit unified `subject_loop` contract is visible over the bionic capsule, with hard invariants from perception through state update
  - Stage31: adapter registry, controlled state-update gate, subject-loop trace/metrics diagnostics, and bionic CLI helper extraction are implemented as offline debt burn-down
  - Stage32: deterministic fallback response shaping replaces the fixed fallback template, exposes `shape` and `context_refs`, and adds `context_shaping_score`
  - Stage33: provider API contracts are inspectable, `openai_compatible` uses chat-completions, and processor-fabric-only model-call boundaries remain explicit
  - Stage34: current technical debt is classified in `holo_host/debt_registry.py`, visual-provider readiness is inspectable without live calls, and `accept-stage34` prevents hidden weak spots or image-capability overclaiming
  - Stage35: internal DeepSeek runtime readiness is machine-checkable, local config is secret-scanned, env-key presence is redacted, and the gate verifies WeChat transport has not been started
  - Stage36: autonomous inquiry formatting debt is closed in the offline bionic kernel; deterministic fallback asks at most one grounded question, exposes inquiry-quality metrics, and preserves action-market-first generation without starting WeChat
  - Stage37: internal bionic self-evaluation now guards provider-backed generation against empty-continuity hallucination, text-provider image overclaiming, excessive question/markdown pressure, and non-speech CLI self-eval empty replies
  - Stage38: explicit bionic CLI image input now routes through `image_understand`, stores image-capable provider metadata in visual memory, and grounds text-only generation in visual summaries without claiming direct raw image access
  - Stage39: internal bionic Turing scoring now gates CLI continuity, naturalness, mechanism-leakage prevention, question bounds, and context grounding
  - Stage40: a bionic brain OS harness now runs bounded CLI/API agent loops with perception, working field, context compiler, deliberation, action-market gating, tool loop, verification, consolidation intent, DeepSeek V4 profiles, operational traces, and agent eval scorecards
  - Stage41: a complete controlled engineering agent now runs CLI/API tool loops with read/search/status/test/write actions, action-market mutation gates, explicit repo-write authority, private-path blocking, verification evidence, traces, and metrics
  - Stage42: an isolated bionic user-simulation performance harness now repeatedly probes first-time-user dialogue quality, high-intensity bionic pressure points, continuity/naturalness/capability honesty/mechanism leakage, and persists only operational eval evidence while the bionic capsule exposes observational `bionic_state`
  - Stage43: a bounded motivational dynamics field now computes replay-stable arousal, valence, uncertainty, curiosity, attachment pressure, fatigue, identity coherence, unfinished-loop pressure, diffuse attention, attention center, and small action-market deltas before action selection
  - Stage48: a biomimetic memory scheduler now separates working memory, hippocampal indices, cortical schemas, salience gates, and diagnostic consolidation targets before prompt/context scheduling without adding a new store or decision layer
  - Stage49: scheduler-owned prompt diet removes duplicate legacy volatile memory blocks, drops empty scheduler slots, and prioritizes recall reconstruction inside the hippocampal budget
  - Stage50: scheduler-owned dynamic compression audit exposes prompt dynamic lines, dropped line counts, compression ratio, and protected-line drop status while preserving DeepSeek live correctness
  - Stage53: upstream MCP tool substrate lets Holo discover and call reviewed stdio MCP tools/resources as external observations through CLI and the Stage41 engineering-agent action market while downstream Holo-as-MCP-server exposure remains deferred
- Post-Stage39 cache diagnostics: exact packet-cache reuse is confirmed live; cache-class homeostasis deficits now require enough packet-cache observations and are rebased from live cache stats instead of stale self-model metadata.
- Post-Stage39 provider-response cache repair: stateless text API providers (`responses`, `openai_compatible`, `deepseek`) now use a bounded QueueStore cache for exact repeated prompts; cache hits are visible as `status=cache_hit` with zero new token cost.
- Post-Stage39 self-dialogue Turing repair: internal CLI probes now guard trace-continuity labels, `revision` vs `vision` marker drift, visible-context questions, exact-memory/image boundaries, non-executable action demotion, theatrical provider wording, and action-market reason leakage before user-facing text. Verified with offline self-dialogue, cached DeepSeek provider probe, full tests, `accept-stage39`, public-release hygiene, and `git diff --check`.
- Stage40 brain harness: internal CLI/API `brain-run` records operational context bundles, phase traces, action-market tool gates, verification evidence, and agent eval scorecards. It does not start WeChat, mutate self-memory, or allow repo/runtime writes by default.
- Stage41 engineering agent: internal CLI/API `engineering-run` executes read/search/status/test/write tool loops through explicit mutation gates. Repo writes require `--allow-repo-write`; private/runtime paths remain blocked; WeChat and self-memory stay untouched.
- Stage42 user simulation: internal CLI/API `run-bionic-user-sim` executes isolated `novice_intro`, dynamic `free_dialogue`, and high-intensity bionic pressure benchmarks. It writes only `agent_eval_runs`, not Mind Graph self-memory, archive memory, or ordinary bionic traces.
- Stage42 bionic structure: every bionic capsule exposes `bionic_state` as an observational surface with bionic-subject positioning, action-market authority, consciousness-field summary, somatic proxy, active intent, uncertainty, continuity pressure, and boundary conditions. It is not a second brain and does not grant runtime authority.
- Stage43 motivational dynamics: every bionic capsule exposes `motivational_field` as a replay-stable internal control field. It can only add bounded action-market score deltas; it cannot select actions directly, write memory, start transport, or become a second decision layer.
- Stage48 memory scheduler: every finalized mind packet exposes `bionic_memory_schedule` as a prompt/context scheduling surface. Cortical schema can enter provider-cache prefix; working memory and hippocampal indices stay dynamic; consolidation targets are diagnostic only and cannot write self-memory directly.
- Stage49 prompt diet: when the scheduler is present, legacy memory blocks no longer duplicate scheduler-owned dynamic memory in the prompt. Recall reconstruction must be carried by `hippocampal_index`, not by restoring the old duplicate `Recall Reconstruction` block.
- Stage50 dynamic compression audit: every scheduler output exposes `prompt_dynamic_lines` and `dynamic_compression_audit`; `protected_line_dropped=true` should be treated as a correctness risk before using cache numbers as improvement evidence.
- Stage42 manual free-dialogue review on `2026-05-10` fixed mechanical fallback phrasing in Chinese: action-market reason leakage, `We were at We...` continuity duplication, broad visual-boundary triggers, and English fallback on Chinese continuation turns. A provider-backed eight-turn probe timed out at `180s`, so long provider-dialogue probes need explicit timeout/cache hardening before being used as acceptance authority.
- The next planned arc is:
  - Stage44+: explicit re-plan for broader provider/API compatibility, richer agent eval suites, replay-backed facade slimming, multimodal user-sim suites, or operator-approved live transport hardening
  - Online long-horizon canary remains deferred beyond Stage28 and must stay replay-first, whitelist-only, rollback-safe, and explicitly re-planned
  - Artifact/tool/outcome progress coupling remains deferred and should not be silently folded into Stage28 or a future canary
  - Bounded subject programs remain deferred beyond the current Stage28 milestone
- This arc must not add a second brain, a new unbounded always-on loop, or transport-side decision logic.

## Source Of Truth
- Public subject-profile templates:
  - `.subject.example.md`
  - `holo_memory_library/subject_seed.example.md`
  - `holo_memory_library/voice_profile.example.md`
- Private local subject-profile files, ignored by Git:
  - `.subject.local.md`
  - `holo_memory_library/subject_seed.md`
  - `holo_memory_library/voice_profile.md`
- Runtime kernel:
  - `holo_host/`
- Long-term and working memory tooling:
  - `holo_memory_library/`
- Private live memory stores, ignored by Git:
  - `holo_memory_library/memories/*.jsonl`
- Operations and recovery:
  - `scripts/`
  - `OPERATIONS.md`
- Windows transport shell:
  - `windows_helper/`

## Current Runtime Truth
- Public/example provider path: `codex_cli`
- Internal local provider path: `deepseek` through the processor fabric when `.holo_host.toml` and `DEEPSEEK_API_KEY` are configured
- Processor fabric is active with three lanes:
  - `kernel_xhigh`
  - `subject_main`
  - `micro_fast`
- Active WeChat online path on this machine: `pyweixin_dialog`
- `wcferry` is diagnostic-only here because local `Weixin 4.1.x` is incompatible with installed `wcferry 39.x`
- WSL is the authoritative kernel
- Windows helper is only the transport shell
- Default brain mode is `full_brain`
- Stage-8 is live:
  - `autobiographical_state`
  - `goal_state`
  - `world_state`
  - `counterfactual`
  - `consciousness_ledger`
- Holo can generate proactive initiative candidates, but current gates are conservative and often block auto-send.
- Stage-9 adaptive initiative gate is implemented in code; rollout should still start from `initiative_gate_mode=conservative` before switching default behavior to `adaptive`.
- Processor routing, provider compatibility, usage accounting, Stage40 brain-harness metrics, Stage41 engineering-agent metrics, Stage42 bionic user-simulation scorecards, and Stage43 motivational-dynamics metrics are now first-class runtime surfaces; new threads should inspect them before changing any model call sites, bionic dialogue behavior, or tool authority.

## Memory Pyramid
- `canonical`: persona core and non-negotiable boundaries
- `durable`: stable long-term memory used in prompt assembly
- `candidate`: emerging patterns waiting for promotion
- `working`: short-lived active observations
- `archive`: full turn ledger, not prompt-facing by default

## Full Dialogue Archive
- Full turn archive file, private/local only:
  - `holo_memory_library/memories/conversation_archive.jsonl`
- CLI conversations are also archived when repo-local Codex hooks are active:
  - `/.codex/hooks.json`
  - `holo_memory_library/codex_hooks/user_prompt_submit.py`
  - `holo_memory_library/codex_hooks/stop_revise.py`
- Quick check for recent CLI archive rows:
  - `python3 holo_memory_library/rag_memory.py show-archive --channel codex_cli --limit 5`

## Mutable Runtime State
These files change while Holo is alive. Do not treat them like static docs, and do not publish them.
- `.holo_runtime/`
- `.holo_runtime/mind_graph.sqlite3`
- `holo_memory_library/memories/working_store.jsonl`
- `holo_memory_library/memories/candidate_store.jsonl`
- `holo_memory_library/memories/memory_store.jsonl`
- `holo_memory_library/memories/conversation_archive.jsonl`
- `holo_memory_library/memories/emotion_trace.jsonl`
- `holo_memory_library/memories/callback_candidates.jsonl`

## Start, Stop, Inspect
- Start all:
  - `./scripts/holo-start-all.sh`
- Stop all:
  - `./scripts/holo-stop-all.sh`
- Restart all:
  - `./scripts/holo-restart-all.sh`
- Status:
  - `./scripts/holo-status.sh`
- Processor routing:
  - `python3 -m holo_host show-processor-routing`
- Provider status:
  - `python3 -m holo_host show-provider-status`
- Provider contracts:
  - `python3 -m holo_host show-provider-contracts`
- Usage ledger:
  - `python3 -m holo_host show-usage-ledger --limit 50`
- Replay calibration fixture:
  - `python3 -m holo_host replay-calibration-fixture --fixture-path tests/fixtures/stage14`
- Replay policy regret:
  - `python3 -m holo_host replay-policy-regret --fixture-path tests/fixtures/stage14`
- Processor fabric acceptance:
  - `python3 -m holo_host accept-processor-fabric`
- Stage14 acceptance:
  - `python3 -m holo_host accept-stage14`
- Stage18 acceptance:
  - `python3 -m holo_host accept-stage18 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage19 acceptance:
  - `python3 -m holo_host accept-stage19 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage19 frontier diagnostics:
  - `python3 -m holo_host show-attention-frontier --channel wechat`
  - `python3 -m holo_host trace-wake-reasons --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-thread-warmth --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage20 temporal diagnostics:
  - `python3 -m holo_host show-open-loops --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-commitments --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-resume-candidate --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage21 policy sediment diagnostics:
  - `python3 -m holo_host show-policy-candidates --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-promoted-policies --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-policy-influence --thread-key TestUser --chat-name TestUser --channel wechat --query "continue this carefully"`
  - `python3 -m holo_host rollback-policy --id <policy_id>`
- Stage22 online canary diagnostics:
  - `python3 -m holo_host show-online-canary`
  - `python3 -m holo_host show-blackbox-metrics --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host show-blackbox-scorecard --since-hours 168`
  - `python3 -m holo_host trace-canary-decision --thread-key TestUser --chat-name TestUser --channel wechat --query "still here?"`
  - `python3 -m holo_host set-canary-rollback --enabled true --reason manual_hold`
  - `python3 -m holo_host replay-live-artifacts --since-hours 24`
  - `python3 -m holo_host export-blind-packets --since-hours 168`
  - `python3 -m holo_host run-blackbox-soak --since-hours 168`
  - `python3 -m holo_host show-world-coupling --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage23 release-parity acceptance:
  - `python3 -m holo_host accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage24 scene-state continuity acceptance:
  - `python3 -m holo_host accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage25 dense continuity diagnostics:
  - `python3 -m holo_host show-continuity-budget --channel wechat`
  - `python3 -m holo_host show-dense-working-set --channel wechat`
  - `python3 -m holo_host trace-thread-pulse --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage25 dense continuity acceptance:
  - `python3 -m holo_host accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage26 task-world diagnostics:
  - `python3 -m holo_host show-task-world --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-world-object --object-id <object_id>`
  - `python3 -m holo_host trace-thread-object-links --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage26 task-world acceptance:
  - `python3 -m holo_host accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage27 long-horizon soak acceptance:
  - `python3 -m holo_host accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage28 multimodal situational diagnostics:
  - `python3 -m holo_host show-situational-field --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"`
  - `python3 -m holo_host trace-visual-field --thread-key TestUser --chat-name TestUser --channel wechat`
  - `python3 -m holo_host trace-inquiry-shaping --thread-key TestUser --chat-name TestUser --channel wechat --query "continue"`
- Stage28 multimodal kernel acceptance:
  - `python3 -m holo_host accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat`
- Stage29 bionic subject-kernel diagnostics:
  - `python3 -m holo_host agent-run --query "continue" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
  - `python3 -m holo_host show-bionic-metrics`
  - `python3 -m holo_host agent-trace --trace-id <trace_id>`
- Stage29 bionic subject-kernel acceptance:
  - `python3 -m holo_host accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage30 unified subject-loop acceptance:
  - `python3 -m holo_host accept-stage30 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage31 debt burn-down diagnostics:
  - `python3 -m holo_host trace-subject-loop --trace-id <trace_id>`
  - `python3 -m holo_host show-subject-loop-metrics`
- Stage31 debt burn-down acceptance:
  - `python3 -m holo_host accept-stage31 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage32 response-shaping acceptance:
  - `python3 -m holo_host accept-stage32 --thread-key TestUser --chat-name TestUser --channel cli`
- Stage33 provider API contract acceptance:
  - `python3 -m holo_host accept-stage33`
- Stage34 debt registry and visual-readiness diagnostics:
  - `python3 -m holo_host show-debt-registry`
  - `python3 -m holo_host show-visual-provider-readiness`
- Stage34 debt registry and visual-readiness acceptance:
  - `python3 -m holo_host accept-stage34`
- Stage35 internal runtime readiness diagnostics:
  - `python3 -m holo_host show-internal-runtime-readiness`
- Stage35 internal runtime readiness acceptance:
  - `python3 -m holo_host accept-stage35`
- Stage36 autonomous inquiry quality acceptance:
  - `python3 -m holo_host accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage37 bionic self-eval and capability-honesty acceptance:
  - `python3 -m holo_host accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage38 visual-provider bridge acceptance:
  - `python3 -m holo_host accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage39 bionic Turing benchmark:
  - `python3 -m holo_host show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage39 bionic Turing benchmark acceptance:
  - `python3 -m holo_host accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage40 bionic brain OS harness:
  - `python3 -m holo_host brain-run --goal "stage40 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2`
  - `python3 -m holo_host brain-trace --trace-id <run_id>`
  - `python3 -m holo_host show-context-bundle --bundle-id <bundle_id>`
  - `python3 -m holo_host show-brain-metrics`
  - `python3 -m holo_host run-agent-eval --suite stage40`
- Stage40 bionic brain OS harness acceptance:
  - `python3 -m holo_host accept-stage40 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage41 complete engineering agent:
  - `python3 -m holo_host engineering-run --goal "inspect current repo" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2`
  - `python3 -m holo_host engineering-run --goal "authorized repair" --thread-key cli:TestUser --chat-name TestUser --channel cli --allow-repo-write`
  - `python3 -m holo_host engineering-trace --trace-id <run_id>`
  - `python3 -m holo_host show-engineering-agent-metrics`
- Stage41 complete engineering agent acceptance:
  - `python3 -m holo_host accept-stage41 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage42 bionic user-simulation performance:
  - `python3 -m holo_host run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
  - `python3 -m holo_host run-bionic-user-sim --thread-key cli:FreeUser --chat-name FreeUser --channel cli --scenario free_dialogue --turns 12 --offline`
  - `python3 -m holo_host show-bionic-user-sim-scorecard --suite novice_intro`
  - `python3 -m holo_host show-bionic-user-sim-scorecard --suite free_dialogue`
- Stage42 bionic user-simulation acceptance:
  - `python3 -m holo_host accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage43 motivational dynamics field acceptance:
  - `python3 -m holo_host accept-stage43 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- Stage15 replay-preserving refactor tests:
  - `pytest -q tests/test_stage15_modularization.py`

## When A New Thread Starts Work
1. Read the docs above in order.
2. Run `./scripts/holo-status.sh`.
3. Run `python3 -m holo_host show-provider-status`.
4. Run `python3 -m holo_host show-processor-routing`.
5. Check whether Holo is supposed to stay online before touching runtime files.
6. Run targeted tests before editing.
7. Make one focused change.
8. Re-run relevant tests.
9. Update docs if runtime behavior, memory semantics, provider routing, or operator workflow changed.

## Where To Look First When Something Breaks
- Kernel health:
  - `./scripts/holo-status.sh`
- WSL runtime logs:
  - `.holo_runtime/logs/`
- Windows watcher log:
  - `.holo_runtime/wechat-helper/receipts/pyweixin_watcher.log`
- Transport heartbeat:
  - `.holo_runtime/wechat-helper/transport_state.live.json`
- Runtime message store:
  - `.holo_runtime/holo_host.sqlite3`
- Mind Graph:
  - `.holo_runtime/mind_graph.sqlite3`
- Full archive:
  - `holo_memory_library/memories/conversation_archive.jsonl`
- Processor routing and cost:
  - `python3 -m holo_host show-processor-routing`
  - `python3 -m holo_host show-provider-status`
  - `python3 -m holo_host show-provider-contracts`
  - `python3 -m holo_host show-visual-provider-readiness`
  - `python3 -m holo_host show-debt-registry`
  - `python3 -m holo_host show-internal-runtime-readiness`
  - `python3 -m holo_host show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli`
  - `python3 -m holo_host show-usage-ledger --limit 100`

## Current Weak Spots
- Canonical classification now lives in `python3 -m holo_host show-debt-registry`; do not delete or soften weak spots without updating that registry and the latest acceptance gate.
- Internal DeepSeek runtime readiness now lives in `python3 -m holo_host show-internal-runtime-readiness`; do not claim Holo is internally runnable until it passes.
- Autonomous inquiry formatting debt is now bounded by `python3 -m holo_host accept-stage36`; do not reintroduce label-template inquiry or multiple ungrounded questions.
- Bionic self-evaluation and capability honesty are now bounded by `python3 -m holo_host accept-stage37`; do not let provider-backed CLI replies invent missing continuity, overclaim image ability, or return empty text for self-eval probes.
- Internal visual-provider bridging is now bounded by `python3 -m holo_host accept-stage38`; explicit CLI images must go through `image_understand`, and text-only generation may describe only visual-memory summaries.
- Internal bionic Turing quality is now bounded by `python3 -m holo_host accept-stage39`; do not let ordinary CLI replies expose internal machinery, reset continuity, or pass scores through formulaic/theatrical phrasing.
- Stage41 engineering-agent authority is bounded by `python3 -m holo_host accept-stage41`; do not allow arbitrary shell commands, default repo writes, private/runtime path access, self-memory mutation, or direct model-to-tool execution.
- Stage42 bionic user-simulation quality is bounded by `python3 -m holo_host accept-stage42`; keep the benchmark isolated as operational eval evidence and do not turn it into runtime decision authority or self-memory.
- `reply_api.py` remains bounded structural debt. Further slimming must happen only behind dedicated compatibility tests, replay checks, and acceptance gates.
- `pyweixin_dialog`, live WeChat trigger behavior, latency/cache/provider-fallback soak, and live visual-provider soak are external-precondition debts while Holo remains WeChat-offline.
- Visual-provider readiness is now bounded by `show-visual-provider-readiness` plus `accept-stage38`: text APIs must not overclaim image support, and explicit CLI image input must preserve image-capable provider metadata.
- Replay fixture breadth remains intentionally narrow and should grow only when it exposes a real blind spot.
- Stage15 helper-module extraction is in place, but facade files are still larger than ideal and should only be slimmed further behind replay checks.

- Stage18 `micro_fast` routing is intentionally conservative; do not broaden it without proving explicit memory/history escalation and action-market-first still hold
- Stage20 temporal state is intentionally bounded and inspectable; do not let it create direct sends, unbounded scheduling, or a second decision layer
- Stage21 policy sediment is intentionally replay-gated and reversible; do not let it become a hard policy override, learned hidden weights, or send-permission bypass
- Stage22 canary is host-side and shadow-first; do not let it pick actions, grant send permission, hide metrics, or turn world-coupling cues into a recall trigger
- Stage25 dense continuity is intentionally bounded and stream-driven; do not let it trigger heavy recall, create a new loop family, or become a watcher-side decision layer
- Stage26 task-world state is intentionally bounded and same-thread-first; do not let it become a second decision layer, a cross-thread hidden coupling path, or a heavy-recall trigger

## Stage-9 Focus
- goal: remove over-conservative proactive gating while preserving hard safety constraints
- hard_gate: non-overridable constraints such as whitelist policy, cooldown, per-thread allow flag, policy decision, and explicit disable
- soft_gate: `trust`, `initiative_window`, `drive_pressure`, `pressure_level` become directional scoring inputs
- main_brain_override: allowed only when gate is soft-blocked and mode is healthy; never bypasses hard_gate
- rollout: begin in `initiative_gate_mode=conservative`, verify, then switch default to adaptive

## Stage-9 Entry Commands
- `python3 -m holo_host initiative-probe --thread-key TestUser --chat-name TestUser`
- `python3 -m holo_host show-initiative-status --thread-key TestUser --chat-name TestUser`
- `python3 -m holo_host accept-stage9 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage12 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage13 --thread-key wechat:TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage14`
- `python3 -m holo_host accept-stage17 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-processor-routing`
- `python3 -m holo_host show-provider-status`
- `python3 -m holo_host accept-stage8 --thread-key TestUser --chat-name TestUser --channel wechat`

## Implemented Subject-Runtime Arc Commands
- `python3 -m holo_host accept-stage18 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-fast-path-metrics --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-predictive-continuity --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-reflex-routing --thread-key TestUser --chat-name TestUser --channel wechat --query "still here?"`
- `python3 -m holo_host accept-stage19 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-attention-frontier --channel wechat`
- `python3 -m holo_host trace-wake-reasons --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-thread-warmth --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage20 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-open-loops --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-commitments --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-resume-candidate --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage21 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-policy-candidates --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-promoted-policies --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-policy-influence --thread-key TestUser --chat-name TestUser --channel wechat --query "continue this carefully"`
- `python3 -m holo_host rollback-policy --id <policy_id>`
- `python3 -m holo_host accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-online-canary`
- `python3 -m holo_host show-blackbox-metrics --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-blackbox-scorecard --since-hours 168`
- `python3 -m holo_host trace-canary-decision --thread-key TestUser --chat-name TestUser --channel wechat --query "still here?"`
- `python3 -m holo_host replay-live-artifacts --since-hours 24`
- `python3 -m holo_host export-blind-packets --since-hours 168`
- `python3 -m holo_host run-blackbox-soak --since-hours 168`
- `python3 -m holo_host show-world-coupling --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-scene-state --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-scene-compression --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-dense-working-set --channel wechat`
- `python3 -m holo_host trace-thread-pulse --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host show-task-world --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host trace-world-object --object-id <object_id>`
- `python3 -m holo_host trace-thread-object-links --thread-key TestUser --chat-name TestUser --channel wechat`
- `python3 -m holo_host agent-run --query "continue" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python3 -m holo_host show-bionic-metrics`
- `python3 -m holo_host show-subject-loop-metrics`
- `python3 -m holo_host show-provider-contracts`
- `python3 -m holo_host show-visual-provider-readiness`
- `python3 -m holo_host show-debt-registry`
- `python3 -m holo_host accept-stage29 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage30 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage31 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage32 --thread-key TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage33`
- `python3 -m holo_host accept-stage34`
- `python3 -m holo_host show-internal-runtime-readiness`
- `python3 -m holo_host accept-stage35`
- `python3 -m holo_host accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host brain-run --goal "stage40 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2`
- `python3 -m holo_host run-agent-eval --suite stage40`
- `python3 -m holo_host accept-stage40 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host engineering-run --goal "stage41 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2`
- `python3 -m holo_host engineering-trace --trace-id <run_id>`
- `python3 -m holo_host show-engineering-agent-metrics`
- `python3 -m holo_host accept-stage41 --thread-key cli:TestUser --chat-name TestUser --channel cli`
- `python3 -m holo_host run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline`
- `python3 -m holo_host show-bionic-user-sim-scorecard --suite novice_intro`
- `python3 -m holo_host accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli`

## Next Arc Program
- Durable Stage23-27 sources of truth:
  - `.agent/PLANS.md`
  - `.agent/STAGE23_27_PROGRAM.md`
- Default sequencing:
  - Stage24 is implemented as the scene-state continuity layer
  - Stage25 is implemented as the dense continuity scheduler and working set
  - Stage26 is implemented as bounded task-world state
  - Stage27 is implemented as the observational long-horizon blackbox soak, scorecard, blind review export, and replay-first follow-up eligibility reporting layer
  - Stage28 is implemented as the multimodal homeostatic kernel over visual memory, scene state, dense continuity, and task-world state
  - Stage29 is implemented as the bionic subject kernel with CLI as first adapter
  - Stage30 is implemented as the unified subject-loop contract
  - Stage31 is implemented as debt burn-down and diagnostics
  - Stage32 is implemented as response shaping and template-pressure reduction
  - Stage33 is implemented as provider API contract hardening
  - Stage34 is implemented as debt registry and visual-readiness hardening
  - Stage35 is implemented as internal DeepSeek runtime readiness
  - Stage36 is implemented as autonomous inquiry quality hardening
  - Stage37 is implemented as bionic self-eval and capability-honesty hardening
  - Stage38 is implemented as the internal visual-provider bridge
  - Stage39 is implemented as the internal bionic Turing benchmark
  - Stage40 is implemented as the internal bionic brain OS harness
  - Stage41 is implemented as the complete controlled engineering agent
  - Online long-horizon canary remains deferred beyond Stage28
  - Bounded subject programs remain deferred until a later explicit re-plan
- Current verified baseline after Stage41:
  - `pytest -q` passed on `2026-04-11` for the Stage23-27 baseline
  - `pytest -q tests/test_stage28_multimodal_homeostatic_kernel.py` passed on `2026-04-28`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage23 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage24 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage25 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage26 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-11`
  - `python3 -m holo_host --config .holo_host.example.toml accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat` passed on `2026-04-28`
  - `pytest -q` passed with `301` tests on `2026-05-10` before Stage39
  - `python -m holo_host --config .holo_host.toml accept-stage36 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-09`
  - `python -m holo_host --config .holo_host.toml accept-stage37 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-09`
  - `python -m holo_host --config .holo_host.toml accept-stage38 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `pytest -q tests/test_stage39_bionic_turing_benchmark.py tests/test_stage38_visual_provider_bridge.py tests/test_stage37_bionic_self_eval.py tests/test_stage36_inquiry_quality.py tests/test_stage32_response_shaping.py tests/test_stage29_bionic_cli_agent.py` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml accept-stage39 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml show-bionic-turing-scorecard --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `pytest -q` passed with `306` tests on `2026-05-10` after Stage39
  - `pytest -q tests/test_stage40_context_compiler.py tests/test_stage40_bionic_brain_harness.py tests/test_stage40_deepseek_v4_profile.py tests/test_stage40_agent_eval.py` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml brain-run --goal "stage40 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml run-agent-eval --suite stage40` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml accept-stage40 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `pytest -q` passed with `331` tests on `2026-05-10` after Stage40
  - `pytest -q tests/test_stage41_engineering_agent.py` passed with `6` tests on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml engineering-run --goal "stage41 smoke" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline --max-steps 2` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml engineering-trace --trace-id 38` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml show-engineering-agent-metrics --limit 5` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml accept-stage41 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `pytest -q` passed with `337` tests on `2026-05-10` after Stage41
  - `pytest -q tests/test_stage42_bionic_user_sim.py tests/test_stage41_engineering_agent.py tests/test_stage39_bionic_turing_benchmark.py` passed with `25` tests on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:TestUser --chat-name TestUser --channel cli --offline` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml show-bionic-user-sim-scorecard --suite novice_intro` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:FreeUser --chat-name FreeUser --channel cli --scenario free_dialogue --turns 8 --offline` passed on `2026-05-10` after manual free-dialogue repair
  - `pytest -q` passed with `343` tests on `2026-05-10` after Stage42 free-dialogue repair
  - `python scripts/check_public_release_hygiene.py` passed on `2026-05-10`
  - `git diff --check` reported no whitespace errors on `2026-05-10`
  - `python -m holo_host --config .holo_host.toml run-bionic-user-sim --thread-key cli:FreeUser --chat-name FreeUser --channel cli --scenario free_dialogue --turns 12 --offline` passed on `2026-05-10` with `issue_count=0` and no WeChat transport start after bionic-state hardening
  - `python -m holo_host --config .holo_host.toml accept-stage42 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-10` with `bionic_state_visible=true`
  - `pytest -q` passed with `346` tests on `2026-05-10` after bionic-state hardening
  - `pytest -q tests/test_stage29_bionic_cli_agent.py tests/test_stage39_bionic_turing_benchmark.py tests/test_stage42_bionic_user_sim.py tests/test_stage43_motivational_dynamics.py` passed with `43` tests on `2026-05-11`
  - `python -m holo_host --config .holo_host.toml accept-stage43 --thread-key cli:TestUser --chat-name TestUser --channel cli` passed on `2026-05-11` with replay-stable bounded motivational dynamics and no WeChat/self-memory side effects
  - `pytest -q` passed with `351` tests on `2026-05-11` after Stage43
  - `python scripts/check_public_release_hygiene.py` passed on `2026-05-11`
  - `git diff --check` reported no whitespace errors on `2026-05-11`
  - Stage29 through Stage43 are offline/internal bionic-kernel/provider/runtime-readiness/inquiry-quality/capability-honesty/visual-provider/bionic-Turing/brain-harness/engineering-agent/user-simulation/motivational-dynamics milestones; run the local verification commands in the latest stage handoff before claiming current green status

## Invariants
- Do not silently change online transport modes
- Do not touch the watcher path without reading `docs/WECHAT_WATCHER_INTERFACE_CONTRACT.md`
- Do not add new direct model call paths outside the processor provider abstraction
- Do not bypass lane routing by hardcoding `codex exec` or raw HTTP calls in random modules
- Do not let internal prompts, hook control text, or rewrite reasons enter durable memory
- Do not let archive be the only place history lives, but also do not let runtime threads become the only continuity
- Do not depend on one Codex thread to keep Holo alive
- Do not forget to keep CLI archive hooks working when editing repo-local hook config
- Do not treat `autobiographical_state`, `goal_state`, or `world_state` as display-only metadata; they are now part of subject deliberation
- Do not publish live memory or runtime state to the public repo
- Do not publish private subject-profile files; only `.example` templates belong in Git
- Do not treat `show-processor-routing`, `show-provider-status`, or `show-usage-ledger` as optional maintenance extras; they are required observability for safe handoff
- Do not enable `canary_live` or restart live services as part of a normal Stage22 code push

## Minimum Done For Any Holo Change
- local behavior works
- tests pass
- state is observable
- docs are updated
- when Stage23-27 planning or runtime sequencing changes, update `.agent/PLANS.md`, `.agent/STAGE23_27_PROGRAM.md`, `HOLO_HANDOFF.md`, and `docs/ROADMAP_REGISTRY.md` together
- another thread can continue from disk without hidden oral context
- when `accept-stage9` is available, run it before and after any gate-mode transition
- when model routing, provider fallback, or token policy changes, run `accept-processor-fabric`
- when calibration or policy quality changes, rerun `accept-stage14` and inspect replay artifacts
