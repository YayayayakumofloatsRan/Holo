from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from . import __version__
from .event_log import EventLog, sanitize
from .hooks import HookManager, event_to_hook_payload, observation_to_hook_payload
from .model import ModelClient, RuleFallbackModel
from .prompt_policy import SYSTEM_PROMPT, assert_no_persona_text
from .schema import AgentResult, Event, Observation
from .self_feedback import evaluate_self_feedback
from .source_authority import build_source_authority_report
from .tools import ToolRegistry
from .web_research_kernel import build_crawl_report, build_search_goal
from .workflow_policy import build_workflow_policy, repair_unverified_engineering_final, verify_engineering_final
from .workspace import load_workspace_context


STOP_REASONS = {
    "final_answer_ready",
    "goal_complete",
    "needs_user_clarification",
    "evidence_exhausted",
    "budget_exhausted",
    "tool_failure_report",
    "boundary_or_permission",
}


@dataclass(slots=True)
class AgentConfig:
    max_steps: int = 10
    log_path: Path = Path(".holo_kernel/events.jsonl")
    model_name: str = "fallback"
    workspace_root: Path = Path.cwd()


@dataclass(slots=True)
class HoloAgent:
    tools: ToolRegistry
    model: ModelClient = field(default_factory=RuleFallbackModel)
    config: AgentConfig = field(default_factory=AgentConfig)
    hooks: HookManager = field(default_factory=HookManager)

    def _action_space(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "answer_direct",
                "description": "Stop tool use and write the final answer from the current observations. Use this when evidence is sufficient.",
                "input_schema": {},
            },
            {
                "name": "ask_clarification",
                "description": "Stop and ask the user a concise clarification question when the goal cannot be resolved from available observations.",
                "input_schema": {"question": "string"},
            },
            *self.tools.specs(),
        ]

    def _emit(self, events: list[Event], kind: str, message: str = "", **data: Any) -> None:
        event = Event(kind=kind, message=message, data=sanitize(data))
        events.append(event)
        EventLog(self.config.log_path).append(event)
        self.hooks.emit(kind, **event_to_hook_payload(event))

    def _enrich_web_search_arguments(self, arguments: dict[str, Any], crawl_report: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(arguments or {})
        query = str(enriched.get("query", "") or "")
        for planned in crawl_report.get("plan", {}).get("queries", []) or []:
            if query and query == planned.get("query"):
                if "allowed_domains" not in enriched and planned.get("allowed_domains"):
                    enriched["allowed_domains"] = list(planned.get("allowed_domains", []))
                if "blocked_domains" not in enriched and planned.get("blocked_domains"):
                    enriched["blocked_domains"] = list(planned.get("blocked_domains", []))
                break
        return enriched

    def run(self, user_text: str) -> AgentResult:
        events: list[Event] = []
        observations: list[Observation] = []
        ok, leaks = assert_no_persona_text(SYSTEM_PROMPT)
        if not ok:
            raise RuntimeError(f"persona text leaked into kernel prompt: {leaks}")

        workspace = load_workspace_context(self.config.workspace_root)
        workflow_policy = build_workflow_policy(user_text)
        search_goal = build_search_goal(user_text)
        context: dict[str, Any] = {
            "system_prompt": SYSTEM_PROMPT,
            "workspace": workspace.to_dict(),
            "workflow_policy": workflow_policy,
            "search_goal": search_goal.to_dict(),
            "step": 0,
        }
        self._emit(events, "goal", user_text)
        self._emit(
            events,
            "context",
            f"instructions={len(workspace.instruction_layers)} skills={len(workspace.skills)}",
            workspace=workspace.to_dict(),
        )
        action_space = self._action_space()
        self._emit(events, "action_space", f"count={len(action_space)}", actions=action_space)
        self._emit(events, "workflow_policy", workflow_policy["task_family"], policy=workflow_policy)

        stop_reason = "budget_exhausted"
        status = "incomplete"
        final = ""
        failed_signatures: set[str] = set()
        decisions: list[dict[str, Any]] = []
        self_feedback_reports: list[dict[str, Any]] = []
        for step in range(self.config.max_steps):
            context["step"] = step
            context["observations"] = [obs.to_dict() for obs in observations]
            context["self_feedback_reports"] = list(self_feedback_reports)
            context["source_authority"] = build_source_authority_report(context["observations"])
            context["crawl_report"] = build_crawl_report(search_goal, context["observations"]).to_dict()
            context["decisions"] = decisions
            decision = self.model.decide(
                user_text=user_text,
                context={k: v for k, v in context.items() if k != "system_prompt"},
                action_space=action_space,
            )
            if decision.action in {"final", "finalize", "respond"}:
                decision.action = "answer_direct"
                decision.reason = (decision.reason + " " if decision.reason else "") + "normalized final action alias"
            decisions.append(decision.to_dict())
            self._emit(events, "model_decide", f"selected={decision.action}", decision=decision.to_dict())

            if decision.action == "answer_direct":
                final = self.model.finalize(
                    user_text=user_text,
                    observations=[obs.to_dict() for obs in observations],
                    context=context,
                )
                engineering_report = verify_engineering_final(final, [obs.to_dict() for obs in observations])
                if engineering_report["status"] != "ok":
                    final = repair_unverified_engineering_final(final, engineering_report)
                    stop_reason = "evidence_exhausted"
                    status = "failed"
                    self._emit(events, "evaluate", f"stop={stop_reason}", engineering_grounding=engineering_report)
                    break
                has_success_observation = any(obs.status == "ok" for obs in observations)
                has_failed_observation = any(obs.status != "ok" for obs in observations)
                last_observation_failed = bool(observations and observations[-1].status != "ok")
                stop_reason = (
                    "tool_failure_report"
                    if last_observation_failed or (has_failed_observation and not has_success_observation)
                    else "final_answer_ready"
                    if observations or decision.can_answer
                    else "evidence_exhausted"
                )
                status = "ok" if stop_reason == "final_answer_ready" else "failed"
                self._emit(events, "evaluate", f"stop={stop_reason}", observation_count=len(observations))
                break

            if decision.action == "ask_clarification":
                final = str(decision.arguments.get("question") or "I need one clarification before continuing.")
                stop_reason = "needs_user_clarification"
                status = "failed"
                self._emit(events, "evaluate", f"stop={stop_reason}", observation_count=len(observations))
                break

            if decision.action == "web_search":
                decision.arguments = self._enrich_web_search_arguments(decision.arguments, context.get("crawl_report", {}))

            self._emit(events, "tool_call", decision.action, arguments=decision.arguments)
            obs = self.tools.run(decision.action, decision.arguments)
            observations.append(obs)
            self.hooks.emit("after_tool", **observation_to_hook_payload(obs))
            self._emit(events, "observation", f"{obs.tool} status={obs.status}", observation=obs.to_dict())
            feedback = evaluate_self_feedback(
                user_text=user_text,
                decision=decision,
                observation=obs,
                context=context,
            )
            self_feedback_reports.append(feedback)
            self._emit(
                events,
                "self_feedback",
                f"{obs.tool} sufficient={str(feedback['evidence_sufficient']).lower()} next={feedback['recommended_next_action']} stop={feedback['canonical_stop_reason']}",
                self_feedback=feedback,
            )

            if obs.status == "ok":
                if step >= self.config.max_steps - 1:
                    final = self.model.finalize(
                        user_text=user_text,
                        observations=[item.to_dict() for item in observations],
                        context=context,
                    )
                    stop_reason = "budget_exhausted"
                    status = "failed"
                    self._emit(events, "evaluate", "observation recorded but decision budget exhausted", stop_reason=stop_reason)
                    break
                self._emit(events, "evaluate", "observation recorded; returning to model", stop_reason="continue")
                continue

            signature = json.dumps({"action": decision.action, "arguments": decision.arguments}, ensure_ascii=False, sort_keys=True)
            if signature in failed_signatures:
                final = self.model.finalize(
                    user_text=user_text,
                    observations=[item.to_dict() for item in observations],
                    context=context,
                )
                stop_reason = "tool_failure_report"
                status = "failed"
                self._emit(events, "evaluate", "same tool action failed again; stopping", stop_reason=stop_reason)
                break
            failed_signatures.add(signature)

            if step >= self.config.max_steps - 1:
                final = self.model.finalize(
                    user_text=user_text,
                    observations=[item.to_dict() for item in observations],
                    context=context,
                )
                stop_reason = "tool_failure_report"
                status = "failed"
                self._emit(events, "evaluate", "tool failed and budget exhausted", stop_reason=stop_reason)
                break

            self._emit(events, "evaluate", "tool failed; retry budget remains", stop_reason="continue")

        if not final:
            final = "No final answer was produced before the step budget was exhausted."
        self._emit(events, "stop", stop_reason)
        self._emit(events, "final", final)
        return AgentResult(
            final=final,
            status=status,
            stop_reason=stop_reason if stop_reason in STOP_REASONS else "budget_exhausted",
            events=events,
            observations=observations,
            metadata={
                "kernel_version": __version__,
                "stage_record": "stage230",
                "model": self.config.model_name,
                "self_feedback_reports": list(self_feedback_reports),
                "search_goal": search_goal.to_dict(),
                "crawl_report": build_crawl_report(search_goal, [obs.to_dict() for obs in observations]).to_dict(),
                "source_authority": build_source_authority_report([obs.to_dict() for obs in observations]),
                "web_provider_health": self.tools.web_provider_health(),
            },
        )
