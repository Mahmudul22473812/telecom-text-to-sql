"""Framework-independent conversation state for the web interface."""

from collections.abc import Callable
from dataclasses import dataclass, field

from .pipeline import PipelineResult, run_pipeline


PipelineRunner = Callable[..., PipelineResult]


@dataclass
class ConversationState:
    """State required to continue clarification across UI reruns."""

    active_question: str | None = None
    clarification_answers: list[str] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)

    @property
    def awaiting_clarification(self) -> bool:
        return self.active_question is not None

    def clear(self) -> None:
        self.active_question = None
        self.clarification_answers = []
        self.messages = []

    def cancel_clarification(self) -> None:
        self.active_question = None
        self.clarification_answers = []


def process_message(
    state: ConversationState,
    message: str,
    *,
    pipeline_runner: PipelineRunner = run_pipeline,
) -> PipelineResult:
    """Process a new question or answer to the pending clarification."""

    cleaned_message = message.strip()
    if not cleaned_message:
        raise ValueError("Message must not be empty.")

    is_clarification_answer = state.awaiting_clarification
    state.messages.append(
        {
            "role": "user",
            "kind": (
                "clarification_answer"
                if is_clarification_answer
                else "question"
            ),
            "content": cleaned_message,
        }
    )

    if is_clarification_answer:
        state.clarification_answers.append(cleaned_message)
    else:
        state.active_question = cleaned_message
        state.clarification_answers = []

    result = pipeline_runner(
        state.active_question,
        clarification_answers=state.clarification_answers,
        execute=True,
    )

    if result.status == "needs_clarification":
        clarification_question = (
            result.clarification_questions[-1]
            if result.clarification_questions
            else "Please clarify your request."
        )
        state.messages.append(
            {
                "role": "assistant",
                "kind": "clarification",
                "content": clarification_question,
            }
        )
    else:
        state.messages.append(
            {
                "role": "assistant",
                "kind": "result",
                "result": result,
            }
        )
        state.cancel_clarification()

    return result
