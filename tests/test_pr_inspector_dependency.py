"""The pr-inspector dependency resolves and exposes the API the runner will build on."""

from pr_inspector.domain.entities import PRReviewResult, RiskLevel
from pr_inspector.infrastructure.git.diff_extractor import GitCliDiffProvider
from pr_inspector.infrastructure.llm.openai_client import OpenAICompatibleLLMReviewer


def test_pr_inspector_exposes_the_api_the_runner_needs():
    assert callable(GitCliDiffProvider.parse_unified_diff)
    assert callable(OpenAICompatibleLLMReviewer.review)
    assert {level.value for level in RiskLevel} == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert {"summary", "risk_level", "issues"} <= set(PRReviewResult.model_fields)
