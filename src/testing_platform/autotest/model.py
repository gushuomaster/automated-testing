"""Model adapter for the agent loop (Anthropic Messages API, also used through compatible relays).

Credentials come from ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL;
they are never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# USD per million tokens (input, output, cache read) at official list price; 5-min cache writes 1.25x input.
# Estimates only: a relay may bill differently.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    calls: int = 0

    def add(self, usage) -> None:
        self.calls += 1
        for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            setattr(self, name, getattr(self, name) + (getattr(usage, name, 0) or 0))

    def cost_usd(self, model: str) -> float | None:
        if model not in PRICES:
            return None
        price_in, price_out, price_cache_read = PRICES[model]
        return round((self.input_tokens * price_in
                      + self.cache_read_input_tokens * price_cache_read
                      + self.cache_creation_input_tokens * price_in * 1.25
                      + self.output_tokens * price_out) / 1e6, 4)

    def to_dict(self, model: str | None = None) -> dict:
        d = {k: getattr(self, k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                           "cache_creation_input_tokens", "calls")}
        if model:
            d["estimated_cost_usd"] = self.cost_usd(model)
        return d


@dataclass
class ClaudeModel:
    model: str = "claude-opus-5-5"
    effort: str | None = "medium"
    max_tokens: int = 12000
    use_cache: bool = True
    timeout: float = 120.0  # per request; the SDK retries, so a hung relay call is abandoned sooner
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        import anthropic

        kwargs = {"max_retries": 4, "timeout": self.timeout}
        if os.environ.get("ANTHROPIC_AUTH_TOKEN") and not os.environ.get("ANTHROPIC_API_KEY"):
            kwargs["auth_token"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
        self.client = anthropic.Anthropic(**kwargs)

    def create(self, system: str, messages: list, tools: list):
        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
            "thinking": {"type": "adaptive"},
        }
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        if self.use_cache:
            params["cache_control"] = {"type": "ephemeral"}
        response = self.client.messages.create(**params)
        self.usage.add(response.usage)
        return response
