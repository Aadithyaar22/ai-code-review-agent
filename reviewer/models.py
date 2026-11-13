"""Data models shared by the engine, CLI, API and formatters."""

from pydantic import BaseModel, Field

SEVERITIES = ["critical", "high", "medium", "low"]
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}  # lower = worse
CATEGORIES = ["bug", "security", "performance", "maintainability", "testing", "style"]


class Finding(BaseModel):
    file: str = ""
    line_start: int
    line_end: int
    severity: str
    category: str
    title: str
    description: str = ""
    fix: str = ""
    evidence: str = ""
    confidence: float = 1.0
    source: str = "llm"  # "llm" or "ruff" / "syntax"
    rule: str = ""  # e.g. ruff code S307


class Report(BaseModel):
    target: str
    language: str = "unknown"
    score: int = 10
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    positives: list[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)

    def count(self, severity: str) -> int:
        return sum(1 for f in self.findings if f.severity == severity)


def compute_score(findings: list[Finding]) -> int:
    """Deterministic 1-10 score from findings (the LLM's own number is noisy)."""
    weights = {"critical": 4.0, "high": 2.0, "medium": 0.75, "low": 0.25}
    penalty = sum(weights.get(f.severity, 0) for f in findings)
    return max(1, min(10, round(10 - penalty)))
