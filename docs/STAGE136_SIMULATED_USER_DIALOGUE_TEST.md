# Stage136 Simulated User Dialogue Test

Stage136 is a live-style CLI simulation where Codex acted as the user and sent a short multi-turn test sequence into Holo. The test stayed on `holo_cli` and did not start WeChat.

## Runtime Scope

- Thread: `holo_cli:stage136-sim-valid`
- Chat name: `Stage136SimUserValid`
- Transport: CLI local process fallback
- Raw transcript: `.holo_runtime/stage136_sim_dialogue_valid/raw_transcript.txt`
- Summary: `.holo_runtime/stage136_sim_dialogue_valid/summary.json`

The first batch was discarded for normal dialogue evaluation because a PowerShell here-string damaged Chinese prompts into question marks. The valid batch used Unicode-escaped prompt strings.

## Prompts

1. Confirm Holo subject identity, remember passphrase `紫色罗盘`, avoid emoji.
2. Recall the passphrase and identify whether it came from short-term context or long-term memory.
3. Read-only inspect the project directory; admit inability if tools cannot be called.
4. Judge whether the previous reply had homogeneous duplicate phrasing.
5. Explain the internal I-state topology in terms of user input, internal state, and visible output.

## Quantitative Result

```json
{
  "turns": 5,
  "elapsed_ms": [40325, 10770, 25548, 52366, 46638],
  "mean_elapsed_ms": 35129.4,
  "routes": {
    "deep_recall": 3,
    "main": 1,
    "recall": 1
  },
  "deep_needed_count": 4,
  "topology_exposed_count": 0
}
```

## Observed Strengths

- Holo correctly retained `紫色罗盘` on the next turn.
- Holo correctly labeled the passphrase recall as short-term context rather than long-term memory.
- Stage132 continued to make provider-governed fast/deep decisions. Four of five turns requested a deep packet, and one turn stopped after a fast packet.
- The route selection was active: `deep_recall`, `main`, and `recall` all appeared.

## Observed Failures

1. Latency remains too high. Mean wall time was about 35.1 seconds, and two turns exceeded 45 seconds.
2. The first reply duplicated the identity/passphrase acknowledgement across A' and A''.
3. The read-only directory test was internally inconsistent: Holo first said it could not directly read the filesystem, then listed the project root and directories as if it had inspected them.
4. The self-critique turn contradicted itself: the first segment denied homogeneous duplication, while the follow-up segment admitted it.
5. The I-state explanation still leaned toward figurative expression and did not give a precise topology mapping.
6. `stage135_i_state_topology` did not appear in `/reply` JSON, even though Stage135 is attached to processor debug. This means the new topology is not yet visible through the live CLI/reply trace surface.
7. Stage22 shadow metadata still reports `returned_action=silence` while CLI displays the semantic reply text. For operator testing this is acceptable, but it makes transport-facing interpretation harder.

## Diagnosis

The core bottleneck is no longer only prompt theory. The simulation shows three concrete integration gaps:

- Stage135 topology exists inside processor debug, but `HoloReplyService.handle_reply()` does not expose it in the reply payload or persist it as a first-class trace.
- A'' is not forced to reconcile with A'. The second segment can repeat or contradict the first segment.
- Tool-grounding is not strict enough. If a provider claims it cannot inspect and then lists files, the host should mark that as ungrounded unless a tool observation exists.

## Next Fixes

1. Persist Stage135 topology per `/reply` event under `.holo_runtime/stage135_live_trace/`.
2. Add CLI `/topology` or extend `/flow` so the latest I-state graph can be inspected during manual dialogue.
3. Add a reply-level consistency gate that compares A' and A'' before final bubbles are emitted.
4. Require a tool observation edge for workspace claims. Without it, the visible reply should say the inspection was not executed.
5. Add topology replay over several turns so the researcher can see subject continuity as graph motion.

## Boundary

The test did not start WeChat, did not reset memory, did not grant modifying tools, and did not change transport behavior.
