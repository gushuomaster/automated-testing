from __future__ import annotations

from typing import Protocol

from testing_platform.domain.execution import ExecutionContext, TestExecutionResult
from testing_platform.domain.test_design import ExecutableTestCase


class TestRunner(Protocol):
    def execute(
        self,
        test_case: ExecutableTestCase,
        context: ExecutionContext,
    ) -> TestExecutionResult: ...


class TestRunnerFactory(Protocol):
    def create(self, context: ExecutionContext) -> TestRunner: ...
