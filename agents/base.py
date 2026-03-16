import json
import time
from abc import ABC, abstractmethod
from typing import Any
import anthropic
from config import settings


class BaseAgent(ABC):
    """Base class for all sub-agents. Handles Claude API calls and audit logging."""

    MODEL_PRIMARY = "claude-sonnet-4-5"
    MODEL_FAST = "claude-haiku-4-5"

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.name = self.__class__.__name__

    def call_claude(
        self,
        system: str,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> tuple[str, float]:
        """Call Claude and return (response_text, cost_usd)."""
        chosen_model = model or self.MODEL_PRIMARY
        start = time.time()
        response = self.client.messages.create(
            model=chosen_model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        latency_ms = int((time.time() - start) * 1000)
        text = response.content[0].text

        # Rough cost estimate (input/output tokens)
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = self._estimate_cost(chosen_model, input_tokens, output_tokens)

        return text, cost, latency_ms

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        rates = {
            "claude-sonnet-4-5": (0.003, 0.015),   # per 1K tokens
            "claude-haiku-4-5":  (0.00025, 0.00125),
        }
        in_rate, out_rate = rates.get(model, (0.003, 0.015))
        return (input_tokens / 1000 * in_rate) + (output_tokens / 1000 * out_rate)

    def parse_json(self, text: str) -> Any:
        """Extract JSON from Claude response (handles markdown code fences)."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        ...
