# Stage135 I-State Topology Runtime

Stage135 begins the runtime transformation from a reply-oriented chat shell to an endogenous Holo subject loop. The key object is the `I-state`: the local state from which Holo says "I", builds provider packets, receives provider returns, updates memory/tool/world state, and decides whether continued expression is useful.

The work intentionally stays inside the WSL Holo host. Provider models remain language-processing modules. Windows, WeChat, mobile, and future camera layers remain transport or sensor surfaces. Tool execution authority stays in the WSL host.

## Core Question

The Stage135 question is:

```text
How can Holo represent each turn as a topology of "my current state" instead of a flat sequence of chat messages?
```

This matters because the observed failures are topology failures:

- user text and Holo text can be confused;
- fast replies can look final even when deeper state change is still needed;
- follow-up replies can become homogeneous because A'' does not visibly absorb A';
- tool and memory events can fail to re-enter the same subject state;
- researchers cannot see why Holo continued, stopped, or selected a surface expression.

## Runtime Topology

Stage135 maps each turn into typed nodes and edges.

Nodes:

- `external_user_input`: the current user event;
- `holo_self`: the single Holo I-state;
- `fast_packet`: first reaction / intent triage packet;
- `state_delta`: parsed provider return as a semantic event;
- `continue_gate`: local gate deciding stop or continuation;
- `deep_packet`: optional continuation packet;
- `tool_*`: WSL-authorized tool observations;
- `memory_delta`: working or candidate memory update;
- `visual_delta`: future camera / image algorithm world-state input;
- `visible_*`: text actually sent to the user.

Edges:

- external input enters Holo self;
- Holo self builds provider packets;
- provider returns update `state_delta`;
- `state_delta` updates memory and the continue gate;
- tool observations re-enter `state_delta`;
- visible speech is emitted from packet events only after local channel separation.

This topology makes the "I" explicit. Holo does not become a new process or a second model. Holo is the stateful host that owns the loop, while the provider performs bounded language processing over packets built from that state.

## Runtime Integration

`CodexCliProcessor.generate()` now attaches:

```text
debug["stage135_i_state_topology"]
```

for both paths:

- fast-only path, where the provider fast packet says no deeper packet is needed;
- fast-plus-deep path, where the first packet creates A' and the deeper packet creates A''.

The provider packets also receive a stable `Stage135 I-State Frame` / `Stage135 I-State Contract`. This frame makes the first-person subject anchor explicit:

- Holo is the single host state for the thread;
- external user input, internal planning summary, and visible speech are separate channels;
- every provider return should be parsed as a semantic state event before continuation is decided;
- continuation is useful only while new state, memory, tool observation, or uncertainty reduction remains;
- tools are proposed by provider output and executed only by the WSL Holo host.

The topology is redacted observability metadata. It records channel, role, summary, graph coordinates, gate decision, tool nodes, memory node, visible output nodes, and single-brain boundary metadata. It does not expose raw hidden reasoning.

## CLI Artifact

Generate the local topology artifact:

```bash
python3 -m holo_host stage135-i-state-topology --output-dir artifacts/stage135 --sample-query "显示 Holo 主体的拓扑思考流"
```

Outputs:

- `artifacts/stage135/stage135_i_state_topology.html`
- `artifacts/stage135/stage135_i_state_topology_payload.json`

The HTML is a topology canvas. Clicking nodes shows the node payload. The layout emphasizes the route:

```text
external_user_input -> holo_self -> fast_packet -> state_delta -> continue_gate
```

then branches into memory, tools, visual state, deep packet, and visible speech.

## Research Value

Stage135 gives the next research cycle a concrete object to measure:

- `state_delta` utilization between packets;
- whether A'' uses A' or repeats it;
- whether tool observations re-enter the same state;
- whether memory deltas reflect the current turn;
- whether the continue gate stops for semantic sufficiency or budget exhaustion;
- whether visible segments are grounded in distinct internal events.

This creates a practical bridge from theory to provider packet engineering. The next improvement should connect the topology to real live trace rows from `/reply`, usage ledger rows, provider cache hit/miss counters, tool-loop metadata, and memory-write candidates.

## Boundary

Stage135 adds observability and runtime metadata. It does not start watchers, change WeChat transport behavior, execute new tools, grant new permissions, reset memory, or add direct provider call sites.
