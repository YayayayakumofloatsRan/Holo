from __future__ import annotations

from kernel_v3.contracts import Feedback


class StopController:
    def should_stop(self, feedback: Feedback) -> bool:
        return feedback.status in {"final_answer_ready", "blocked", "needs_user_input"}
