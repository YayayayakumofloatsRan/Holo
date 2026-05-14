from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .common import compact_text, utc_now


INNER_STREAM_NAME = "inner_stream"
INNER_STREAM_PHASES = (
    "sensory_edge",
    "attention_focus",
    "affective_tension",
    "memory_echo",
    "goal_pressure",
    "inhibition_gate",
    "candidate_action",
)


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _compact(value: Any, limit: int = 160) -> str:
    return compact_text(str(value or "").strip(), limit)


def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value or 0.0)))


def _metric(value: Any, default: float = 0.0) -> float:
    try:
        return _clamp(float(value))
    except (TypeError, ValueError):
        return _clamp(default)


def _signed_metric(value: Any, default: float = 0.0) -> float:
    try:
        current = float(value)
    except (TypeError, ValueError):
        current = float(default)
    return max(-1.0, min(1.0, current))


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _json_dict(text: str) -> dict[str, Any]:
    current = str(text or "").strip()
    if not current:
        return {}
    try:
        loaded = json.loads(current)
    except json.JSONDecodeError:
        return {}
    return dict(loaded) if isinstance(loaded, dict) else {}


def _latest_loop_signal(brain_status: dict[str, Any]) -> tuple[str, str]:
    loops = [dict(item) for item in _as_list(brain_status.get("loops")) if isinstance(item, dict)]
    active = [item for item in loops if str(item.get("status", "") or "").strip() not in {"", "never", "idle"}]
    source = active[0] if active else (loops[0] if loops else {})
    loop_name = _compact(source.get("loop_name"), 60)
    summary = _compact(
        source.get("influence_summary")
        or source.get("blocked_reason")
        or source.get("status")
        or "baseline cortical noise",
        180,
    )
    return loop_name or "baseline", summary


def _build_biological_surrogate(
    *,
    previous: dict[str, Any],
    plasticity: dict[str, Any],
    previous_attractor: str,
    dominant_attractor: str,
    memory_echo: str,
    recent_micro: list[str],
    prediction_error: float,
    salience_delta: float,
    affective_input: float,
    salience: float,
    activation_energy: float,
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    previous_modulators = _as_dict(previous.get("neuromodulators"))
    attractor_changed = dominant_attractor != previous_attractor
    dopamine_target = _clamp(0.1 + prediction_error * 0.7 + (0.08 if attractor_changed else 0.0))
    norepinephrine_target = _clamp(0.08 + affective_input * 0.62 + salience_delta * 0.22)
    acetylcholine_target = _clamp(0.12 + salience * 0.6 + prediction_error * 0.16)
    serotonin_target = _clamp(0.65 - affective_input * 0.35 - prediction_error * 0.18 + (-0.04 if attractor_changed else 0.06))
    neuromodulators = {
        "dopamine": round(_clamp(_metric(previous_modulators.get("dopamine"), 0.12) * 0.72 + dopamine_target * 0.28), 4),
        "norepinephrine": round(
            _clamp(_metric(previous_modulators.get("norepinephrine"), 0.1) * 0.7 + norepinephrine_target * 0.3),
            4,
        ),
        "acetylcholine": round(
            _clamp(_metric(previous_modulators.get("acetylcholine"), 0.18) * 0.72 + acetylcholine_target * 0.28),
            4,
        ),
        "serotonin": round(_clamp(_metric(previous_modulators.get("serotonin"), 0.45) * 0.78 + serotonin_target * 0.22), 4),
    }

    previous_neural = _as_dict(previous.get("neural_field"))
    excitatory_target = _clamp(
        activation_energy * 0.52
        + neuromodulators["dopamine"] * 0.18
        + neuromodulators["acetylcholine"] * 0.12
        + salience * 0.18
    )
    inhibitory_target = _clamp(0.1 + activation_energy * 0.42 + neuromodulators["norepinephrine"] * 0.2 + affective_input * 0.18)
    excitatory_tone = _clamp(_metric(previous_neural.get("excitatory_tone"), 0.08) * 0.68 + excitatory_target * 0.32)
    inhibitory_tone = _clamp(_metric(previous_neural.get("inhibitory_tone"), 0.12) * 0.72 + inhibitory_target * 0.28)
    thalamic_target = _clamp(
        0.08
        + neuromodulators["acetylcholine"] * 0.48
        + neuromodulators["norepinephrine"] * 0.22
        + neuromodulators["serotonin"] * 0.08
    )
    thalamic_gain = _clamp(_metric(previous_neural.get("thalamic_gain"), 0.12) * 0.7 + thalamic_target * 0.3)
    replay_novelty = 0.2 if memory_echo and memory_echo != str(plasticity.get("last_memory_echo", "") or "") else 0.05
    hippocampal_target = _clamp(0.04 + replay_novelty + min(1.0, len(recent_micro) / 6.0) * 0.12 + salience * 0.12)
    hippocampal_replay = _clamp(_metric(previous_neural.get("hippocampal_replay"), 0.0) * 0.76 + hippocampal_target * 0.24)
    global_workspace_ignition = _clamp(
        activation_energy * 0.38
        + salience * 0.22
        + thalamic_gain * 0.18
        + neuromodulators["dopamine"] * 0.12
        - inhibitory_tone * 0.1
    )
    e_i_balance = _signed_metric(excitatory_tone - inhibitory_tone)
    if activation_energy >= 0.68 or e_i_balance >= 0.18:
        homeostatic_response = "increase_inhibition"
    elif activation_energy <= 0.18 and inhibitory_tone > excitatory_tone:
        homeostatic_response = "release_inhibition"
    else:
        homeostatic_response = "hold_balance"
    neural_field = {
        "excitatory_tone": round(excitatory_tone, 4),
        "inhibitory_tone": round(inhibitory_tone, 4),
        "e_i_balance": round(e_i_balance, 4),
        "thalamic_gain": round(thalamic_gain, 4),
        "hippocampal_replay": round(hippocampal_replay, 4),
        "global_workspace_ignition": round(global_workspace_ignition, 4),
    }

    previous_synaptic = _as_dict(plasticity.get("synaptic_trace"))
    ltp = _clamp(
        _metric(previous_synaptic.get("ltp"), 0.0) * 0.74
        + prediction_error * 0.18
        + salience_delta * 0.14
        + neuromodulators["dopamine"] * 0.08
        + (0.05 if attractor_changed else 0.0)
    )
    ltd = _clamp(_metric(previous_synaptic.get("ltd"), 0.0) * 0.78 + inhibitory_tone * 0.22)
    consolidation_pressure = _clamp(
        _metric(previous_synaptic.get("consolidation_pressure"), 0.0) * 0.84 + hippocampal_replay * 0.12 + ltp * 0.08
    )
    synaptic_trace = {
        "ltp": round(ltp, 4),
        "ltd": round(ltd, 4),
        "consolidation_pressure": round(consolidation_pressure, 4),
        "potentiated_attractor": dominant_attractor,
        "homeostatic_response": homeostatic_response,
        "attractor_transition": f"{previous_attractor} -> {dominant_attractor}",
    }
    return neuromodulators, neural_field, synaptic_trace


@dataclass(slots=True)
class InnerStreamRuntime:
    """Volatile runtime buffer for endogenous subject-state micro-ticks."""

    max_ticks: int = 64
    _sequence: int = 0
    _ticks: list[dict[str, Any]] = field(default_factory=list)
    _field_state: dict[str, Any] = field(
        default_factory=lambda: {
            "activation_energy": 0.0,
            "prediction_error": 0.0,
            "salience": 0.0,
            "affective_tension": 0.08,
            "dominant_attractor": "baseline",
            "recurrence_depth": 0,
            "neuromodulators": {
                "dopamine": 0.12,
                "norepinephrine": 0.1,
                "acetylcholine": 0.18,
                "serotonin": 0.45,
            },
            "neural_field": {
                "excitatory_tone": 0.08,
                "inhibitory_tone": 0.12,
                "e_i_balance": -0.04,
                "thalamic_gain": 0.12,
                "hippocampal_replay": 0.0,
                "global_workspace_ignition": 0.0,
            },
        }
    )
    _plasticity_trace: dict[str, Any] = field(
        default_factory=lambda: {
            "recent_micro_thoughts": [],
            "attractor_counts": {},
            "last_memory_echo": "",
            "synaptic_trace": {
                "ltp": 0.0,
                "ltd": 0.0,
                "consolidation_pressure": 0.0,
                "potentiated_attractor": "baseline",
                "homeostatic_response": "baseline",
                "attractor_transition": "baseline -> baseline",
            },
        }
    )

    def _update_field(
        self,
        *,
        attention_focus: str,
        memory_echo: str,
        micro_thought: str,
        processor_payload: dict[str, Any],
        processor_invoked: bool,
        baseline_tension: float,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        previous = dict(self._field_state)
        plasticity = dict(self._plasticity_trace)
        recent_micro = [str(item) for item in _as_list(plasticity.get("recent_micro_thoughts")) if str(item).strip()]
        previous_micro = recent_micro[-1] if recent_micro else ""
        previous_attractor = _compact(previous.get("dominant_attractor"), 100) or "baseline"
        explicit_prediction = processor_payload.get("prediction_error")
        prediction_error = _metric(explicit_prediction, 0.05 if processor_invoked else 0.0)
        salience_delta = _metric(processor_payload.get("salience_delta"), 0.08 if processor_invoked else 0.0)
        affective_input = _metric(processor_payload.get("affective_tension"), baseline_tension)
        salience = _clamp(float(previous.get("salience", 0.0) or 0.0) * 0.82 + salience_delta)
        activation_energy = _clamp(
            float(previous.get("activation_energy", 0.0) or 0.0) * 0.86
            + 0.08
            + prediction_error * 0.25
            + salience_delta * 0.35
            + affective_input * 0.2
        )
        dominant_attractor = _compact(attention_focus, 100) or previous_attractor
        neuromodulators, neural_field, synaptic_trace = _build_biological_surrogate(
            previous=previous,
            plasticity=plasticity,
            previous_attractor=previous_attractor,
            dominant_attractor=dominant_attractor,
            memory_echo=memory_echo,
            recent_micro=recent_micro,
            prediction_error=prediction_error,
            salience_delta=salience_delta,
            affective_input=affective_input,
            salience=salience,
            activation_energy=activation_energy,
        )
        counts = dict(plasticity.get("attractor_counts", {})) if isinstance(plasticity.get("attractor_counts", {}), dict) else {}
        counts[dominant_attractor] = int(counts.get(dominant_attractor, 0) or 0) + 1
        recent_micro.append(micro_thought)
        recent_micro = recent_micro[-6:]
        updated_plasticity = {
            "recent_micro_thoughts": recent_micro,
            "attractor_counts": counts,
            "last_memory_echo": memory_echo,
            "synaptic_trace": synaptic_trace,
        }
        recurrence_depth = int(previous.get("recurrence_depth", 0) or 0) + 1
        updated_field = {
            "activation_energy": round(activation_energy, 4),
            "prediction_error": round(prediction_error, 4),
            "salience": round(salience, 4),
            "affective_tension": round(affective_input, 4),
            "dominant_attractor": dominant_attractor,
            "recurrence_depth": recurrence_depth,
            "neuromodulators": neuromodulators,
            "neural_field": neural_field,
        }
        recurrent_context = {
            "previous_micro_thought": previous_micro,
            "previous_attractor": previous_attractor,
            "recurrence_depth": recurrence_depth,
        }
        self._field_state = dict(updated_field)
        self._plasticity_trace = dict(updated_plasticity)
        return updated_field, updated_plasticity, recurrent_context

    def tick(
        self,
        *,
        mode: str,
        idle_seconds: float,
        latest_activity_at: str,
        brain_status: dict[str, Any],
        processor_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._sequence += 1
        loop_name, loop_signal = _latest_loop_signal(brain_status)
        processor = _as_dict(processor_result)
        processor_metadata = _as_dict(processor.get("metadata"))
        processor_text = _compact(processor.get("text"), 600)
        processor_payload = _json_dict(processor_text)
        processor_status = _compact(processor.get("status") or ("ok" if int(processor.get("returncode", 0) or 0) == 0 else "error"), 40)
        processor_invoked = bool(processor)
        has_activity = bool(str(latest_activity_at or "").strip())
        idle = max(0.0, float(idle_seconds or 0.0)) if has_activity else 0.0
        sensory_edge = (
            f"idle:{round(idle, 2)}s since {latest_activity_at}"
            if has_activity
            else "no external activity recorded; endogenous baseline tick"
        )
        attention_focus = _compact(processor_payload.get("attention_focus"), 180) or f"{loop_name}:{loop_signal}"
        affective_tension = round(min(1.0, 0.08 + idle / 3600.0), 4)
        memory_echo = _compact(processor_payload.get("memory_echo"), 180) or (
            loop_signal if loop_signal != "baseline cortical noise" else "no salient recall yet"
        )
        goal_pressure = _compact(processor_payload.get("goal_pressure"), 140) or (
            "preserve_continuity" if mode in {"companion", "full_brain"} else "maintain_runtime_integrity"
        )
        inhibition_gate = _compact(processor_payload.get("inhibition_gate"), 160) or "volatile_only:no_transport:no_policy:no_self_memory"
        candidate_action = _compact(processor_payload.get("candidate_action"), 120) or "continue_inner_flow"
        micro_thought = (
            _compact(processor_payload.get("micro_thought"), 220)
            or _compact(processor_payload.get("summary"), 220)
            or _compact(processor_text, 220)
            or "local baseline tick"
        )
        field_state, plasticity_trace, recurrent_context = self._update_field(
            attention_focus=attention_focus,
            memory_echo=memory_echo,
            micro_thought=micro_thought,
            processor_payload=processor_payload,
            processor_invoked=processor_invoked,
            baseline_tension=affective_tension,
        )

        tick = {
            "stream_name": INNER_STREAM_NAME,
            "status": "flowing" if processor_status in {"", "ok"} else "error",
            "blocked_reason": ""
            if processor_status in {"", "ok"}
            else _compact(processor.get("stderr") or processor.get("error") or processor_status, 180),
            "sequence": self._sequence,
            "created_at": utc_now(),
            "mode": str(mode or ""),
            "phase_order": list(INNER_STREAM_PHASES),
            "processor_invoked": processor_invoked,
            "micro_thought": micro_thought,
            "field_state": field_state,
            "plasticity_trace": plasticity_trace,
            "recurrent_context": recurrent_context,
            "sensory_edge": sensory_edge,
            "attention_focus": attention_focus,
            "affective_tension": affective_tension,
            "memory_echo": memory_echo,
            "goal_pressure": goal_pressure,
            "inhibition_gate": inhibition_gate,
            "candidate_action": candidate_action,
            "authority": {
                "memory_write": "volatile_ring_only",
                "self_memory_write": False,
                "policy_write": False,
                "transport_write": False,
                "model_call": processor_invoked,
            },
            "processor": {
                "status": processor_status or "skipped",
                "provider": _compact(processor_metadata.get("provider"), 80),
                "model": _compact(processor_metadata.get("model"), 120),
                "lane": _compact(processor_metadata.get("lane"), 80),
                "returncode": int(processor.get("returncode", 0) or 0),
            },
            "motifs": [loop_name, goal_pressure],
        }
        self._ticks.append(tick)
        if len(self._ticks) > max(1, int(self.max_ticks or 1)):
            del self._ticks[: len(self._ticks) - max(1, int(self.max_ticks or 1))]
        return dict(tick)

    def state(self) -> dict[str, Any]:
        latest = dict(self._ticks[-1]) if self._ticks else {}
        return {
            "stream_name": INNER_STREAM_NAME,
            "sequence": self._sequence,
            "phase_order": list(INNER_STREAM_PHASES),
            "latest_tick": latest,
            "recent_ticks": [dict(item) for item in self._ticks],
            "field_state": dict(self._field_state),
            "plasticity_trace": dict(self._plasticity_trace),
            "authority": {
                "memory_write": "volatile_ring_only",
                "self_memory_write": False,
                "policy_write": False,
                "transport_write": False,
                "model_call": bool(latest.get("processor_invoked", False)),
            },
        }
