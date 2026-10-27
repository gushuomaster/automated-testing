from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from testing_platform.ports.agent_gateway import AgentRequest, AgentResponse, AgentUsage

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_requirement_prerun.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("run_requirement_prerun", SCRIPT_PATH)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
SCRIPT_MODULE = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(SCRIPT_MODULE)
BudgetExceeded = SCRIPT_MODULE.BudgetExceeded
BudgetedGateway = SCRIPT_MODULE.BudgetedGateway


class FakeGateway:
    def __init__(self, responses: list[AgentResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def run(self, request: AgentRequest) -> AgentResponse:
        self.calls += 1
        return self.responses.pop(0)


def request() -> AgentRequest:
    return AgentRequest(task_type="requirement_analysis", user_input="输入", parameters={"stage": "extract"})


def limits(**overrides: int) -> dict[str, int]:
    return {"max_agent_calls": 2, "max_input_tokens": 100, "max_output_tokens": 100, **overrides}


def usage() -> dict:
    return {"agent_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "token_usage_complete": True, "violations": [], "calls": []}


def test_budgeted_gateway_counts_calls_and_blocks_calls_over_the_limit():
    upstream = FakeGateway([AgentResponse(usage=AgentUsage(input_tokens=10, output_tokens=5)) for _ in range(3)])
    gateway = BudgetedGateway(upstream, usage(), limits(max_agent_calls=1))

    gateway.run(request())
    with pytest.raises(BudgetExceeded, match="调用次数"):
        gateway.run(request())

    assert upstream.calls == 1


def test_budgeted_gateway_records_token_overrun_and_does_not_return_response():
    upstream = FakeGateway([AgentResponse(usage=AgentUsage(input_tokens=101, output_tokens=5))])
    accounting = usage()
    gateway = BudgetedGateway(upstream, accounting, limits())

    with pytest.raises(BudgetExceeded, match="超出冻结"):
        gateway.run(request())

    assert accounting["agent_calls"] == 1
    assert accounting["input_tokens"] == 101
    assert accounting["violations"] == ["INPUT_TOKENS_EXCEEDED"]
    assert accounting["calls"] == [{"stage": "extract", "input_tokens": 101, "output_tokens": 5}]
    with pytest.raises(BudgetExceeded, match="预算已耗尽"):
        gateway.run(request())
    assert upstream.calls == 1


def test_budgeted_gateway_marks_missing_token_usage_incomplete():
    upstream = FakeGateway([AgentResponse()])
    accounting = usage()

    BudgetedGateway(upstream, accounting, limits()).run(request())

    assert accounting["agent_calls"] == 1
    assert accounting["token_usage_complete"] is False
    assert accounting["calls"] == [{"stage": "extract", "input_tokens": None, "output_tokens": None}]
