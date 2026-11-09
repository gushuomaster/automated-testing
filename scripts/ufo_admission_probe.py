"""Offline-testable guard for UFO's native LocalCommandDispatcher.

This is a local admission probe, not an agent or a replacement execution loop.
Only explicit single-click attempts are input-budgeted. Native focus operations,
swallowed controller errors and synchronous work surviving cancellation are not
measured here; this wrapper alone cannot establish full UFO admission.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import time
from typing import Any, Callable


class AdmissionDenied(RuntimeError):
    """A command was refused before the native dispatcher was called."""


class NativeExecutionFailed(RuntimeError):
    """The native dispatcher returned a failed or incomplete result."""


class RestrictedUFODispatcher:
    """Wrap a real dispatcher's ``execute_commands`` without importing UFO.

    ``selected_window`` and ``control_window`` must inspect trusted live UIA
    objects and return (process_id, top_level_handle), never model parameters.
    Install this wrapper as ``context.command_dispatcher``; keep the underlying
    dispatcher and its UI-server registrations inaccessible to model tools.
    Only the reviewed UI server may own the permitted tool names.

    The probe fixes the window for its lifetime (no rebinding). All batches are
    prevalidated, then dispatched one command at a time with repeated deadline,
    window and retry checks. A failing command stops the rest of its batch.
    """

    _READ_FIELDS = frozenset({
        "get_app_window_info", "get_app_window_controls_info",
        "get_app_window_controls_target_info",
    })

    def __init__(
        self,
        native_dispatcher: Any,
        *,
        target_window: tuple[int, int],
        selected_window: Callable[[], tuple[int, int]],
        control_window: Callable[[str], tuple[int, int] | None],
        max_seconds: float = 30,
        max_inputs: int = 2,
        max_same_action_retries: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (len(target_window) != 2 or any(type(v) is not int or v <= 0 for v in target_window)):
            raise ValueError("target_window must contain positive process ID and handle")
        if not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("max_seconds must be finite and positive")
        if type(max_inputs) is not int or max_inputs < 0:
            raise ValueError("max_inputs must be a nonnegative integer")
        if type(max_same_action_retries) is not int or max_same_action_retries < 0:
            raise ValueError("max_same_action_retries must be a nonnegative integer")
        self._native = native_dispatcher
        self._target = tuple(target_window)
        self._selected_window = selected_window
        self._control_window = control_window
        self._clock = clock
        self._deadline = clock() + max_seconds
        self._max_inputs = max_inputs
        self._max_failures = max_same_action_retries + 1
        self._failed_actions: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self.inputs_attempted = 0
        self.commands_attempted = 0
        self.failures = 0
        self.events: list[dict[str, Any]] = []

    def _deny(self, code: str) -> None:
        self.events.append({"event": "denied", "code": code})
        raise AdmissionDenied(code)

    def _validate(self, command: Any) -> tuple[str, int]:
        if self._clock() >= self._deadline:
            self._deny("deadline")
        if self._selected_window() != self._target:
            self._deny("window_scope")
        name = getattr(command, "tool_name", None)
        kind = getattr(command, "tool_type", None)
        params = getattr(command, "parameters", None)
        if type(name) is not str or type(kind) is not str:
            self._deny("tool_not_allowed")
        if type(params) is not dict:
            self._deny("parameters")
        cost = 0
        if name in self._READ_FIELDS and kind == "data_collection":
            if set(params) != {"field_list"} or type(params["field_list"]) is not list:
                self._deny("parameters")
            if not all(type(value) is str for value in params["field_list"]):
                self._deny("parameters")
        elif name == "get_ui_tree" and kind == "data_collection":
            if params:
                self._deny("parameters")
        elif name == "click_input" and kind == "action":
            allowed = {"id", "name", "button", "double"}
            if not {"id", "name"} <= set(params) or not set(params) <= allowed:
                self._deny("parameters")
            if any(type(params[key]) is not str or not params[key] for key in ("id", "name")):
                self._deny("parameters")
            if self._control_window(params["id"]) != self._target:
                self._deny("control_scope")
            if params.get("button", "left") != "left" or params.get("double", False) is not False:
                self._deny("compound_input")
            cost = 1
        else:
            self._deny("tool_not_allowed")
        encoded = json.dumps([kind, name, params], sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if self._failed_actions.get(fingerprint, 0) >= self._max_failures:
            self._deny("retry_limit")
        return fingerprint, cost

    def _failed(self, name: str, fingerprint: str) -> None:
        self.failures += 1
        self._failed_actions[fingerprint] = self._failed_actions.get(fingerprint, 0) + 1
        self.events.append({"event": "failed", "tool": name, "fingerprint": fingerprint})

    async def execute_commands(self, commands: list[Any], timeout: float = 6000) -> list[Any]:
        """Delegate native Command objects, preserving their Result objects.

        Denials/failures raise and are terminal for the current batch. The caller
        must not retry via an unwrapped dispatcher. No automatic retry occurs.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            self._deny("timeout")
        async with self._lock:
            if type(commands) is not list or not commands:
                self._deny("batch")
            snapshot = copy.deepcopy(commands)
            plan = [self._validate(command) for command in snapshot]
            if sum(cost for _, cost in plan) > self._max_inputs - self.inputs_attempted:
                self._deny("input_budget")
            results = []
            for command in snapshot:
                fingerprint, cost = self._validate(command)
                if self.inputs_attempted + cost > self._max_inputs:
                    self._deny("input_budget")
                remaining = min(timeout, self._deadline - self._clock())
                if remaining <= 0:
                    self._deny("deadline")
                self.inputs_attempted += cost
                self.commands_attempted += 1
                name = command.tool_name
                self.events.append({"event": "attempt", "tool": name, "input_cost": cost,
                                    "fingerprint": fingerprint})
                try:
                    outcome = await asyncio.wait_for(
                        self._native.execute_commands([command], timeout=remaining), remaining
                    )
                except BaseException:
                    self._failed(name, fingerprint)
                    raise
                if (not isinstance(outcome, list) or len(outcome) != 1
                        or getattr(outcome[0], "status", None) != "success"
                        or getattr(outcome[0], "error", None)):
                    self._failed(name, fingerprint)
                    raise NativeExecutionFailed("native_failure_or_incomplete_result")
                self.events.append({"event": "success", "tool": name, "fingerprint": fingerprint})
                results.extend(outcome)
            return results
