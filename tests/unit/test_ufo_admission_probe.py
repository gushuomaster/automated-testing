from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    "ufo_admission_probe", Path(__file__).resolve().parents[2] / "scripts/ufo_admission_probe.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Native:
    def __init__(self, statuses=None):
        self.calls = []
        self.statuses = iter(statuses or [])

    async def execute_commands(self, commands, timeout):
        self.calls.append((commands, timeout))
        status = next(self.statuses, "success")
        if isinstance(status, BaseException):
            raise status
        return [SimpleNamespace(status=status, error=None)]


def command(tool="click_input", kind="action", **params):
    if tool in {"click_input", "texts"}:
        params = {"id": "1", "name": "页签", **params}
    return SimpleNamespace(tool_name=tool, tool_type=kind, parameters=params)


def guard(native=None, **kwargs):
    return MODULE.RestrictedUFODispatcher(
        native or Native(), target_window=(50, 100), selected_window=lambda: (50, 100),
        control_window=kwargs.pop("control_window", lambda _: (50, 100)), **kwargs
    )


def run(dispatcher, commands):
    return asyncio.run(dispatcher.execute_commands(commands))


@pytest.mark.parametrize("name", [
    "capture_window_screenshot", "capture_desktop_screenshot", "execute_command",
    "run_command", "write_to_cells", "execute_com", "get_desktop_app_info",
    "select_application_window", "set_edit_text", "keyboard_input", "click_on_coordinates",
])
def test_forbidden_tools_never_reach_native_callback(name):
    native = Native()
    dispatcher = guard(native)
    with pytest.raises(MODULE.AdmissionDenied, match="tool_not_allowed"):
        run(dispatcher, [command(name)])
    assert native.calls == []
    assert dispatcher.commands_attempted == 0


def test_texts_cannot_focus_control_without_spending_input_budget():
    native = Native()
    dispatcher = guard(native, max_inputs=0)
    with pytest.raises(MODULE.AdmissionDenied, match="tool_not_allowed"):
        run(dispatcher, [command("texts")])
    assert native.calls == []
    assert dispatcher.commands_attempted == dispatcher.inputs_attempted == 0


@pytest.mark.parametrize("params", [
    {"double": True}, {"double": 0}, {"button": "right"}, {"clicks": 2},
    {"actions": ["click", "click"]}, {"id": ["1", "2"]}, {"name": {"command": "shell"}},
    {"process_id": 50}, {"window_handle": 100},
])
def test_compound_or_self_reported_scope_is_rejected(params):
    native = Native()
    with pytest.raises(MODULE.AdmissionDenied):
        run(guard(native), [command(**params)])
    assert native.calls == []


def test_foreign_control_and_changed_selected_window_block_execution():
    native = Native()
    with pytest.raises(MODULE.AdmissionDenied, match="control_scope"):
        run(guard(native, control_window=lambda _: (51, 101)), [command()])
    dispatcher = guard(native)
    dispatcher._selected_window = lambda: (50, 101)
    with pytest.raises(MODULE.AdmissionDenied, match="window_scope"):
        run(dispatcher, [command()])
    assert native.calls == []


def test_batch_preflight_prevents_partial_execution_and_overspend():
    native = Native()
    dispatcher = guard(native, max_inputs=1)
    with pytest.raises(MODULE.AdmissionDenied, match="tool_not_allowed"):
        run(dispatcher, [command(), command("capture_desktop_screenshot")])
    with pytest.raises(MODULE.AdmissionDenied, match="input_budget"):
        run(dispatcher, [command(), command()])
    assert native.calls == []
    assert dispatcher.inputs_attempted == 0


@pytest.mark.parametrize("failure", ["failure", "skipped", RuntimeError("native failed")])
def test_failed_attempt_consumes_input_and_blocks_second_input(failure):
    native = Native([failure])
    dispatcher = guard(native, max_inputs=1)
    with pytest.raises((MODULE.NativeExecutionFailed, RuntimeError)):
        run(dispatcher, [command()])
    with pytest.raises(MODULE.AdmissionDenied, match="input_budget"):
        run(dispatcher, [command()])
    assert len(native.calls) == 1
    assert dispatcher.inputs_attempted == dispatcher.failures == 1


def test_two_retries_means_original_plus_two_failures_and_no_fourth_call():
    native = Native(["failure"] * 4)
    dispatcher = guard(native, max_inputs=10, max_same_action_retries=2)
    for _ in range(3):
        with pytest.raises(MODULE.NativeExecutionFailed):
            run(dispatcher, [command()])
    with pytest.raises(MODULE.AdmissionDenied, match="retry_limit"):
        run(dispatcher, [command()])
    assert len(native.calls) == dispatcher.inputs_attempted == dispatcher.failures == 3


def test_batch_stops_after_failed_first_command():
    native = Native(["failure"])
    dispatcher = guard(native)
    with pytest.raises(MODULE.NativeExecutionFailed):
        run(dispatcher, [command(), command()])
    assert len(native.calls) == 1


def test_deadline_is_rechecked_between_commands():
    now = [0.0]

    class AdvancingNative(Native):
        async def execute_commands(self, commands, timeout):
            result = await super().execute_commands(commands, timeout)
            now[0] = 11.0
            return result

    native = AdvancingNative()
    dispatcher = guard(native, max_seconds=10, clock=lambda: now[0])
    with pytest.raises(MODULE.AdmissionDenied, match="deadline"):
        run(dispatcher, [command(), command()])
    assert len(native.calls) == dispatcher.inputs_attempted == 1
    assert native.calls[0][1] <= 10


def test_successful_read_keeps_native_result_and_costs_no_input():
    native = Native()
    dispatcher = guard(native, max_inputs=0)
    results = run(dispatcher, [command("get_ui_tree", "data_collection")])
    assert results[0].status == "success"
    assert dispatcher.commands_attempted == 1
    assert dispatcher.inputs_attempted == dispatcher.failures == 0


def test_expired_deadline_blocks_first_callback():
    now = [0.0]
    native = Native()
    dispatcher = guard(native, clock=lambda: now[0], max_seconds=1)
    now[0] = 1.0
    with pytest.raises(MODULE.AdmissionDenied, match="deadline"):
        run(dispatcher, [command()])
    assert native.calls == []


def test_missing_native_result_is_a_failed_attempt():
    class MissingNative(Native):
        async def execute_commands(self, commands, timeout):
            self.calls.append((commands, timeout))
            return None

    native = MissingNative()
    dispatcher = guard(native)
    with pytest.raises(MODULE.NativeExecutionFailed):
        run(dispatcher, [command()])
    assert len(native.calls) == dispatcher.inputs_attempted == dispatcher.failures == 1


def test_concurrent_batches_cannot_spend_the_same_remaining_input():
    native = Native()
    dispatcher = guard(native, max_inputs=1)

    async def concurrent():
        return await asyncio.gather(
            dispatcher.execute_commands([command()]), dispatcher.execute_commands([command()]),
            return_exceptions=True,
        )

    results = asyncio.run(concurrent())
    assert sum(isinstance(value, MODULE.AdmissionDenied) for value in results) == 1
    assert len(native.calls) == dispatcher.inputs_attempted == 1
