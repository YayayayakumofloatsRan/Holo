from __future__ import annotations

from kernel_v3.contracts import CandidateAction, ContextBundle, Feedback, Observation


class FakePlanner:
    def __init__(self, actions: list[CandidateAction]) -> None:
        self._actions = list(actions)
        self.calls: list[ContextBundle] = []

    @classmethod
    def respond_once(cls, text: str) -> "FakePlanner":
        return cls(
            [
                CandidateAction(
                    action_id="act-respond",
                    kind="respond",
                    name=None,
                    description="respond to user",
                    score=1.0,
                    payload={"text": text},
                    reasons=["direct answer"],
                    side_effect_class="none",
                )
            ]
        )

    def propose(self, context: ContextBundle, feedback: Feedback | None = None) -> CandidateAction:
        self.calls.append(context)
        if not self._actions:
            raise AssertionError("FakePlanner has no more actions")
        return self._actions.pop(0)


class FakeEvaluator:
    def __init__(self, feedbacks: list[dict[str, object]]) -> None:
        self._feedbacks = list(feedbacks)
        self.calls: list[Observation] = []

    @classmethod
    def final_answer(cls, answer: str) -> "FakeEvaluator":
        return cls(
            [
                {
                    "status": "final_answer_ready",
                    "stop_reason": "completed",
                    "answer": answer,
                    "missing_evidence": [],
                }
            ]
        )

    @classmethod
    def needs_user_input(cls, answer: str) -> "FakeEvaluator":
        return cls(
            [
                {
                    "status": "needs_user_input",
                    "stop_reason": "needs_user_input",
                    "answer": answer,
                    "missing_evidence": [],
                }
            ]
        )

    @classmethod
    def stop_on_block(cls) -> "FakeEvaluator":
        return cls(
            [
                {
                    "status": "blocked",
                    "stop_reason": "blocked",
                    "answer": None,
                    "missing_evidence": [],
                }
            ]
        )

    def evaluate(self, context: ContextBundle, observation: Observation) -> Feedback:
        self.calls.append(observation)
        if not self._feedbacks:
            raise AssertionError("FakeEvaluator has no more feedback")
        data = self._feedbacks.pop(0)
        return Feedback(
            feedback_id=f"fb-{len(self.calls)}",
            run_id=str(context.state["run_id"]),
            status=str(data["status"]),
            stop_reason=data.get("stop_reason") if isinstance(data.get("stop_reason"), str) else None,
            answer=data.get("answer") if isinstance(data.get("answer"), str) else None,
            missing_evidence=list(data.get("missing_evidence", [])),
        )
