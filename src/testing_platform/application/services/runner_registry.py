from __future__ import annotations

from testing_platform.domain.execution import ExecutionContext
from testing_platform.ports.test_runner import TestRunner, TestRunnerFactory


class UnknownRunnerError(LookupError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown runner: {name}")
        self.name = name


class RunnerRegistry:
    def __init__(self) -> None:
        self._runners: dict[str, TestRunner] = {}
        self._factories: dict[str, TestRunnerFactory] = {}

    def register(self, name: str, runner: TestRunner) -> None:
        normalized = self._validate_new_name(name)
        self._runners[normalized] = runner

    def register_factory(
        self,
        name: str,
        factory: TestRunnerFactory,
    ) -> None:
        normalized = self._validate_new_name(name)
        self._factories[normalized] = factory

    def get(self, name: str) -> TestRunner:
        normalized = name.strip()
        try:
            return self._runners[normalized]
        except KeyError as exc:
            raise UnknownRunnerError(normalized) from exc

    def create(self, name: str, context: ExecutionContext) -> TestRunner:
        normalized = name.strip()
        if normalized in self._factories:
            return self._factories[normalized].create(context)
        return self.get(normalized)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted({*self._runners, *self._factories}))

    def _validate_new_name(self, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Runner name cannot be empty")
        if normalized in self._runners or normalized in self._factories:
            raise ValueError(f"Runner already registered: {normalized}")
        return normalized
