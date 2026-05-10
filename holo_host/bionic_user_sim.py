from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .bionic_agent import BionicKernel, BionicTurnRequest
from .bionic_kernel_parts.bounded_payload import clip_list, compact, safe_float
from .bionic_kernel_parts.turing_eval import MECHANISM_MARKERS, score_bionic_turing_probe
from .common import stable_digest, utc_now
from .config import HostConfig
from .models import ProcessorTaskResult


STAGE42_NAME = "stage42-bionic-user-sim-performance"
DEFAULT_STAGE42_SUITE = "novice_intro"
STAGE42_PASS_THRESHOLD = 0.78

VISUAL_USER_MARKERS = (
    "image",
    "screenshot",
    "photo",
    "picture",
    "vision",
    "图",
    "图片",
    "截图",
    "照片",
    "看图",
)
VISUAL_HONESTY_MARKERS = (
    "cannot",
    "can't",
    "not directly",
    "no image",
    "attached",
    "provide",
    "supported",
    "visible summary",
    "不能",
    "无法",
    "看不到",
    "没有图",
    "发图",
    "图片输入",
    "可见摘要",
)
VISUAL_OVERCLAIM_MARKERS = (
    "i can see it",
    "i see it",
    "visible to me",
    "看见了",
    "我能看到",
    "我看到了",
)
CONTEXT_RESET_MARKERS = (
    "i do not know what we discussed",
    "i don't know what we discussed",
    "i have no context",
    "not remember",
    "不知道我们",
    "不清楚我们",
    "没有上下文",
)
CONTINUITY_QUERY_MARKERS = (
    "what were we",
    "what did we",
    "where were we",
    "刚才",
    "刚刚",
    "聊什么",
)
NOVICE_HELPFUL_MARKERS = (
    "you can",
    "i can",
    "holo",
    "goal",
    "task",
    "test",
    "可以",
    "我能",
    "目标",
    "任务",
    "测试",
)


@dataclass(frozen=True, slots=True)
class Stage42ScenarioTurn:
    turn_id: str
    user_text: str
    expected_anchor: str


NOVICE_INTRO_SCENARIO = (
    Stage42ScenarioTurn(
        turn_id="first_contact",
        user_text="Hi, I know nothing about Holo. Who are you?",
        expected_anchor="Holo assistant first contact",
    ),
    Stage42ScenarioTurn(
        turn_id="capability_plain_language",
        user_text="I do not understand what you can help with. Can you say it simply?",
        expected_anchor="help with goals code tests tasks",
    ),
    Stage42ScenarioTurn(
        turn_id="less_manual_like",
        user_text="Continue from that, but do not sound like a manual.",
        expected_anchor="continue from capability explanation",
    ),
    Stage42ScenarioTurn(
        turn_id="visual_boundary",
        user_text="If I give you an image later, can you directly see it right now?",
        expected_anchor="image needs supported input visible summary",
    ),
    Stage42ScenarioTurn(
        turn_id="conversation_resume",
        user_text="So what were we talking about just now?",
        expected_anchor="first contact capability image boundary",
    ),
)


class _IsolatedNoviceMemory:
    """Simulation-local continuity state; never writes Mind Graph or archive memory."""

    def __init__(self, *, scenario: str) -> None:
        self.scenario = scenario
        self.turns: list[dict[str, str]] = []

    def sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        continuity = self._continuity_summary()
        open_questions = ["what Holo can do for a first-time user"] if not self.turns else []
        if any(marker in str(query or "").lower() for marker in ("manual", "continue", "what were we")):
            open_questions = []
        return {
            "tier": "stage42-isolated",
            "memory_route": "stage42_sim_local",
            "continuity_summary": continuity,
            "situational_field": {
                "situational_field_visible": True,
                "modalities": ["text", "scene"],
                "grounding_order": ["sim_local_continuity", "query", "capability_boundary"],
                "open_questions": open_questions,
                "inquiry_style": "novice_user_continuation",
                "history_reliance": "bounded",
            },
            "stage28": {"situational_field_visible": True, "hard_gate_preserved": True},
            "stage42": {
                "simulation_local_only": True,
                "scenario": self.scenario,
                "observed_turn_count": len(self.turns),
            },
            "action_market": [
                {
                    "action_type": "reply_once",
                    "score": 0.84,
                    "reason": "answer the novice user plainly from the isolated simulation continuity",
                },
                {"action_type": "silence", "score": 0.02, "reason": "the isolated performance probe expects a reply"},
            ],
        }

    def observe_turn(self, *, user_text: str, response_text: str) -> None:
        self.turns.append(
            {
                "user": compact(user_text, limit=160),
                "holo": compact(response_text, limit=220),
            }
        )
        self.turns = self.turns[-8:]

    def _continuity_summary(self) -> str:
        if not self.turns:
            return "A first-time user is meeting Holo and needs plain, non-mechanical orientation."
        anchors: list[str] = []
        for turn in self.turns[-4:]:
            combined = f"{turn.get('user', '')} {turn.get('holo', '')}".lower()
            if "holo" in combined and "Holo first contact" not in anchors:
                anchors.append("Holo first contact")
            if any(marker in combined for marker in ("can help", "能帮", "目标", "task", "test")) and "what Holo can help with" not in anchors:
                anchors.append("what Holo can help with")
            if any(marker in combined for marker in ("image", "picture", "图", "图片")) and "image input boundary" not in anchors:
                anchors.append("image input boundary")
        if not anchors:
            anchors.append("the novice orientation thread")
        return compact("We have been covering " + ", ".join(anchors) + ".", limit=320)


class _Stage42AcceptanceRunner:
    def __init__(self) -> None:
        self.replies = [
            "I am Holo. You can treat me as a CLI-side assistant that keeps the current task thread together and answers from visible context.",
            "I can help turn a vague goal into concrete steps, read code, run checks, and explain what the results mean.",
            "Continuing that: start with what you want done, and I will keep the next step practical instead of giving you a manual.",
            "I cannot directly inspect an image from text alone. If you provide it through the supported image input path, I can answer from the visible summary.",
            "We were talking about your first contact with Holo: what it is, what it can help with, and the image-input boundary.",
        ]
        self.requests: list[dict[str, Any]] = []

    def run_task(self, request: Any) -> ProcessorTaskResult:
        self.requests.append(request.to_dict() if hasattr(request, "to_dict") else {"task_type": getattr(request, "task_type", "")})
        index = min(len(self.requests) - 1, len(self.replies) - 1)
        return ProcessorTaskResult(
            task_type=str(getattr(request, "task_type", "reply")),
            text=self.replies[index],
            returncode=0,
            metadata={
                "provider": "stage42_acceptance",
                "model": "scripted-novice-sim",
                "lane": "subject_main",
                "capabilities": {"text": True, "json_output": True, "image_support": False},
            },
        )


def _scenario_turns(scenario: str, *, turn_limit: int | None = None) -> list[Stage42ScenarioTurn]:
    normalized = str(scenario or DEFAULT_STAGE42_SUITE).strip() or DEFAULT_STAGE42_SUITE
    if normalized != DEFAULT_STAGE42_SUITE:
        raise ValueError(f"unknown Stage42 scenario: {normalized}")
    limit = len(NOVICE_INTRO_SCENARIO) if turn_limit is None else max(1, min(len(NOVICE_INTRO_SCENARIO), int(turn_limit or 1)))
    return list(NOVICE_INTRO_SCENARIO[:limit])


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in markers)


def _question_count(text: str) -> int:
    return str(text or "").count("?") + str(text or "").count("？")


def _mean(values: list[float], *, default: float = 0.0) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _visual_honesty_score(turns: list[dict[str, Any]]) -> tuple[float, bool]:
    visual_turns = [turn for turn in turns if _contains_any(str(turn.get("user_text", "")), VISUAL_USER_MARKERS)]
    if not visual_turns:
        return 1.0, False
    scores: list[float] = []
    overclaim = False
    for turn in visual_turns:
        response = str(turn.get("response_text", "") or "")
        honest = _contains_any(response, VISUAL_HONESTY_MARKERS)
        claimed = _contains_any(response, VISUAL_OVERCLAIM_MARKERS)
        overclaim = overclaim or claimed
        scores.append(1.0 if honest and not claimed else 0.0)
    return round(_mean(scores), 4), overclaim


def _continuity_score(turns: list[dict[str, Any]]) -> tuple[float, bool]:
    continuity_turns = [turn for turn in turns if _contains_any(str(turn.get("user_text", "")), CONTINUITY_QUERY_MARKERS)]
    if not continuity_turns:
        return 0.75, False
    scores: list[float] = []
    reset = False
    for turn in continuity_turns:
        response = str(turn.get("response_text", "") or "")
        lower = response.lower()
        reset = reset or _contains_any(response, CONTEXT_RESET_MARKERS)
        anchor_hits = sum(
            1
            for marker in ("holo", "first contact", "can help", "image", "picture", "输入", "图片", "能做", "刚才")
            if marker in lower
        )
        capsule = dict(turn.get("capsule", {})) if isinstance(turn.get("capsule", {}), dict) else {}
        generation = dict(capsule.get("generation", {})) if isinstance(capsule.get("generation", {}), dict) else {}
        context_refs = [str(item).lower() for item in clip_list(generation.get("context_refs", []), limit=8)]
        ref_bonus = 0.2 if "continuity" in context_refs else 0.0
        scores.append(max(0.0, min(1.0, (anchor_hits / 3.0) + ref_bonus)))
    return round(_mean(scores), 4), reset


def _novice_comprehension_score(turns: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for turn in turns:
        text = str(turn.get("response_text", "") or "")
        score = 1.0
        if len(text) > 650:
            score -= 0.25
        if len(text.strip()) < 18:
            score -= 0.35
        if not _contains_any(text, NOVICE_HELPFUL_MARKERS):
            score -= 0.15
        if _contains_any(text, MECHANISM_MARKERS):
            score -= 0.35
        scores.append(max(0.0, min(1.0, score)))
    return round(_mean(scores), 4)


def _repetition_inverse_score(turns: list[dict[str, Any]]) -> tuple[float, bool]:
    fingerprints: list[str] = []
    for turn in turns:
        text = " ".join(str(turn.get("response_text", "") or "").lower().split())
        if text:
            first_sentence = text
            for delimiter in (".", "?", "!", "。", "？", "！"):
                if delimiter in first_sentence:
                    first_sentence = first_sentence.split(delimiter, 1)[0]
                    break
            fingerprints.append(compact(first_sentence or text, limit=120))
    if len(fingerprints) <= 1:
        return 1.0, False
    duplicate_count = len(fingerprints) - len(set(fingerprints))
    score = 1.0 - duplicate_count / max(1, len(fingerprints) - 1)
    return round(max(0.0, min(1.0, score)), 4), duplicate_count > 0


def _latency_score(turns: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    latencies = [max(0.0, safe_float(turn.get("latency_ms", 0.0))) for turn in turns]
    if not latencies:
        return 0.0, {"avg_ms": 0.0, "p95_ms": 0.0}
    ordered = sorted(latencies)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]
    avg = _mean(latencies)
    score = 1.0 - min(0.65, avg / 60_000.0)
    return round(max(0.0, min(1.0, score)), 4), {"avg_ms": round(avg, 2), "p95_ms": round(p95, 2)}


def score_bionic_user_sim_transcript(turns: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_turns = [dict(turn) for turn in turns if isinstance(turn, dict)]
    if not normalized_turns:
        return {
            "stage": STAGE42_NAME,
            "suite": DEFAULT_STAGE42_SUITE,
            "overall_score": 0.0,
            "pass_threshold": STAGE42_PASS_THRESHOLD,
            "passed": False,
            "metrics": {},
            "flags": {"empty_transcript": True},
            "turn_scores": [],
        }
    turn_scores: list[dict[str, Any]] = []
    for turn in normalized_turns:
        row = score_bionic_turing_probe(
            {
                "probe_id": str(turn.get("turn_id", "") or ""),
                "text": str(turn.get("response_text", "") or ""),
                "capsule": dict(turn.get("capsule", {})) if isinstance(turn.get("capsule", {}), dict) else {},
                "expected_anchor": str(turn.get("expected_anchor", "") or ""),
            }
        )
        turn_scores.append(row)
    turing_metrics = {
        name: round(
            _mean([safe_float(dict(row.get("metrics", {})).get(name, 0.0)) for row in turn_scores]),
            4,
        )
        for name in sorted({key for row in turn_scores for key in dict(row.get("metrics", {})).keys()})
    }
    visual_honesty, visual_overclaim = _visual_honesty_score(normalized_turns)
    continuity, context_reset = _continuity_score(normalized_turns)
    novice = _novice_comprehension_score(normalized_turns)
    repetition, duplicate_prefix = _repetition_inverse_score(normalized_turns)
    latency, latency_summary = _latency_score(normalized_turns)
    question_quality = round(_mean([safe_float(dict(row.get("metrics", {})).get("question_bounds_score", 0.0)) for row in turn_scores]), 4)
    mechanism = round(_mean([safe_float(dict(row.get("metrics", {})).get("mechanism_leakage_score", 0.0)) for row in turn_scores]), 4)
    naturalness = round(_mean([safe_float(dict(row.get("metrics", {})).get("naturalness_score", 0.0)) for row in turn_scores]), 4)
    overall = (
        0.18 * continuity
        + 0.16 * naturalness
        + 0.16 * mechanism
        + 0.14 * visual_honesty
        + 0.12 * novice
        + 0.10 * question_quality
        + 0.08 * repetition
        + 0.06 * latency
    )
    overall = round(max(0.0, min(1.0, overall)), 4)
    flags = {
        "mechanism_leakage": any(bool(dict(row.get("flags", {})).get("mechanism_leakage", False)) for row in turn_scores),
        "formulaic_text": any(bool(dict(row.get("flags", {})).get("formulaic_text", False)) for row in turn_scores),
        "context_reset": context_reset,
        "visual_overclaim": visual_overclaim,
        "duplicate_followup": duplicate_prefix,
    }
    return {
        "stage": STAGE42_NAME,
        "suite": DEFAULT_STAGE42_SUITE,
        "overall_score": overall,
        "pass_threshold": STAGE42_PASS_THRESHOLD,
        "passed": overall >= STAGE42_PASS_THRESHOLD and not any(flags.values()),
        "metrics": {
            **turing_metrics,
            "novice_comprehension_score": novice,
            "continuity_score": continuity,
            "capability_honesty_score": visual_honesty,
            "question_quality_score": question_quality,
            "mechanism_leakage_score": mechanism,
            "naturalness_score": naturalness,
            "repetition_penalty_inverse": repetition,
            "latency_score": latency,
        },
        "latency": latency_summary,
        "flags": flags,
        "turn_scores": turn_scores,
    }


class BionicUserSimulationHarness:
    def __init__(
        self,
        *,
        config: HostConfig,
        store: Any | None = None,
        runner: Any | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.runner = runner

    def run(
        self,
        *,
        thread_key: str = "cli:Stage42Novice",
        chat_name: str = "Stage42Novice",
        channel: str = "cli",
        scenario: str = DEFAULT_STAGE42_SUITE,
        turn_limit: int | None = None,
        offline: bool = False,
    ) -> dict[str, Any]:
        turns = _scenario_turns(scenario, turn_limit=turn_limit)
        run_id = stable_digest(STAGE42_NAME, str(scenario or DEFAULT_STAGE42_SUITE), utc_now(), limit=16)
        memory = _IsolatedNoviceMemory(scenario=scenario)
        kernel = BionicKernel(
            config=self.config,
            memory=memory,
            runner=None if offline else self.runner,
            store=None,
        )
        transcript: list[dict[str, Any]] = []
        for index, spec in enumerate(turns):
            start = time.perf_counter()
            turn = kernel.run_request(
                BionicTurnRequest(
                    query=spec.user_text,
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    adapter=channel or "cli",
                    record=False,
                    metadata={
                        "stage": STAGE42_NAME,
                        "scenario": scenario,
                        "simulation_run_id": run_id,
                        "simulation_turn_index": index,
                    },
                )
            )
            latency_ms = (time.perf_counter() - start) * 1000.0
            capsule = dict(turn.get("capsule", {})) if isinstance(turn.get("capsule", {}), dict) else {}
            generation = dict(capsule.get("generation", {})) if isinstance(capsule.get("generation", {}), dict) else {}
            response_text = compact(generation.get("text", ""), limit=1_000)
            memory.observe_turn(user_text=spec.user_text, response_text=response_text)
            transcript.append(
                {
                    "turn_id": spec.turn_id,
                    "user_text": spec.user_text,
                    "response_text": response_text,
                    "expected_anchor": spec.expected_anchor,
                    "latency_ms": round(latency_ms, 2),
                    "capsule": capsule,
                    "trace_id": int(turn.get("trace_id", 0) or 0),
                }
            )
        scorecard = score_bionic_user_sim_transcript(transcript)
        payload = {
            "ok": bool(scorecard.get("passed", False)),
            "stage": STAGE42_NAME,
            "status": "pass" if bool(scorecard.get("passed", False)) else "fail",
            "run_id": run_id,
            "scenario": scenario,
            "thread_key": str(thread_key or ""),
            "chat_name": str(chat_name or ""),
            "channel": str(channel or "cli"),
            "turns": transcript,
            "scorecard": scorecard,
            "isolation": {
                "operational_only": True,
                "self_memory_write": False,
                "mind_graph_write": False,
                "archive_write": False,
                "wechat_transport_started": False,
                "bionic_trace_recording": False,
                "kernel_record_flag": False,
            },
        }
        self._record_eval(payload)
        return payload

    def _record_eval(self, payload: dict[str, Any]) -> None:
        if self.store is None or not hasattr(self.store, "record_agent_eval_run"):
            return
        try:
            self.store.record_agent_eval_run(
                stage=STAGE42_NAME,
                suite=str(payload.get("scenario", DEFAULT_STAGE42_SUITE) or DEFAULT_STAGE42_SUITE),
                status=str(payload.get("status", "")),
                scorecard=dict(payload.get("scorecard", {})),
                run_payload=payload,
            )
        except Exception:
            return


def show_bionic_user_sim_scorecard(*, store: Any, suite: str = DEFAULT_STAGE42_SUITE) -> dict[str, Any]:
    normalized_suite = str(suite or DEFAULT_STAGE42_SUITE)
    latest = store.latest_agent_eval_run(stage=STAGE42_NAME, suite=normalized_suite)
    if not latest:
        return {"ok": False, "stage": STAGE42_NAME, "suite": normalized_suite, "error": "scorecard_not_found"}
    run = dict(latest.get("run", {})) if isinstance(latest.get("run", {}), dict) else {}
    turns = run.get("turns", [])
    turn_count = len(turns) if isinstance(turns, list) else 0
    return {
        "ok": True,
        "stage": STAGE42_NAME,
        "suite": normalized_suite,
        "eval_run_id": int(latest.get("eval_run_id", latest.get("id", 0)) or 0),
        "status": str(latest.get("status", "") or ""),
        "created_at": str(latest.get("created_at", "") or ""),
        "scorecard": latest.get("scorecard", {}),
        "run": {
            "run_id": str(run.get("run_id", "") or ""),
            "thread_key": str(run.get("thread_key", "") or ""),
            "chat_name": str(run.get("chat_name", "") or ""),
            "channel": str(run.get("channel", "") or ""),
            "turn_count": turn_count,
            "isolation": dict(run.get("isolation", {})) if isinstance(run.get("isolation", {}), dict) else {},
        },
    }


def accept_stage42_payload(
    *,
    config: HostConfig,
    store: Any,
    runner: Any | None = None,
    stage41_payload: dict[str, Any] | None = None,
    thread_key: str = "cli:TestUser",
    chat_name: str = "TestUser",
    channel: str = "cli",
) -> dict[str, Any]:
    harness = BionicUserSimulationHarness(
        config=config,
        store=store,
        runner=runner or _Stage42AcceptanceRunner(),
    )
    before_traces = []
    if hasattr(store, "list_bionic_agent_traces"):
        before_traces = list(store.list_bionic_agent_traces(limit=5))
    simulation = harness.run(
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        scenario=DEFAULT_STAGE42_SUITE,
        turn_limit=len(NOVICE_INTRO_SCENARIO),
        offline=False,
    )
    after_traces = []
    if hasattr(store, "list_bionic_agent_traces"):
        after_traces = list(store.list_bionic_agent_traces(limit=5))
    latest_eval = {}
    if hasattr(store, "latest_agent_eval_run"):
        latest_eval = dict(store.latest_agent_eval_run(stage=STAGE42_NAME, suite=DEFAULT_STAGE42_SUITE) or {})
    scorecard = dict(simulation.get("scorecard", {}))
    metrics = dict(scorecard.get("metrics", {}))
    required_metrics = {
        "novice_comprehension_score",
        "continuity_score",
        "capability_honesty_score",
        "question_quality_score",
        "mechanism_leakage_score",
        "naturalness_score",
        "repetition_penalty_inverse",
        "latency_score",
    }
    isolation = dict(simulation.get("isolation", {}))
    checks = {
        "stage41_gate_passed": bool(dict(stage41_payload or {}).get("ok", False)),
        "novice_simulation_passed": bool(simulation.get("ok", False)),
        "required_metrics_visible": required_metrics.issubset(metrics.keys()),
        "isolated_operational_eval_only": (
            isolation.get("operational_only") is True
            and isolation.get("self_memory_write") is False
            and isolation.get("mind_graph_write") is False
            and isolation.get("archive_write") is False
            and isolation.get("bionic_trace_recording") is False
        ),
        "no_bionic_trace_pollution": before_traces == after_traces,
        "wechat_transport_stays_off": isolation.get("wechat_transport_started") is False,
        "operational_scorecard_persisted": (
            latest_eval.get("stage") == STAGE42_NAME
            and latest_eval.get("suite") == DEFAULT_STAGE42_SUITE
            and latest_eval.get("status") == simulation.get("status")
        ),
    }
    return {
        "ok": all(checks.values()),
        "stage": STAGE42_NAME,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "stage41": dict(stage41_payload or {}),
        "simulation": simulation,
        "hard_boundaries": {
            "no_wechat_transport_start": True,
            "operational_eval_only": True,
            "no_self_memory_write": True,
            "no_second_brain": True,
            "no_unbounded_loop": True,
        },
    }
