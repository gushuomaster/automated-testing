from __future__ import annotations

from pydantic import Field

from testing_platform.domain.documents import StrictModel
from testing_platform.domain.requirements import ParsedRequirements


class QuickRegressionResult(StrictModel):
    expected_ids: list[str]
    actual_ids: list[str]
    missing_ids: list[str]
    unexpected_ids: list[str]
    duplicate_ids: list[str]
    missing_sources: list[str]
    forbidden_values: list[str]
    passed: bool
    limitations: list[str] = Field(default_factory=lambda: [
        "只检查编号、来源存在和禁止词，不衡量语义精确率或召回率。",
        "历史输出不能作为正式真值。",
    ])


def quick_regression(parsed: ParsedRequirements, expected_ids: list[str], forbidden: list[str]) -> QuickRegressionResult:
    actual = [item.id for item in parsed.requirements]
    duplicates = sorted({identifier for identifier in actual if actual.count(identifier) > 1})
    text = parsed.model_dump_json()
    result = QuickRegressionResult(
        expected_ids=expected_ids, actual_ids=actual,
        missing_ids=sorted(set(expected_ids) - set(actual)), unexpected_ids=sorted(set(actual) - set(expected_ids)),
        duplicate_ids=duplicates,
        missing_sources=[item.id for item in parsed.requirements if not item.source_evidence],
        forbidden_values=[item for item in forbidden if item in text], passed=False,
    )
    result.passed = not any((result.missing_ids, result.unexpected_ids, result.duplicate_ids,
                             result.missing_sources, result.forbidden_values))
    return result
