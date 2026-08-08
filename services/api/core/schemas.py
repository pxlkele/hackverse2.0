"""
Frozen contracts.

Both tracks code against these. If you need a change, say so out loud — a silent
edit here breaks the other person's work.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EligibilityStatus(str, Enum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEED_INFO = "need_info"


class Profile(BaseModel):
    """What the user told us. Facts only — no judgements, no assumptions."""

    raw_text: str = ""
    language: str = "hi"

    name: str | None = None
    age: int | None = None
    gender: Literal["male", "female", "other"] | None = None

    occupation: str | None = None
    occupation_category: (
        Literal["street_vendor", "artisan", "farmer", "trader", "service", "other"] | None
    ) = None
    years_in_business: float | None = None
    sells_food: bool | None = None

    daily_income: float | None = None
    monthly_income: float | None = None

    state: str | None = None
    city: str | None = None

    documents: list[str] = Field(default_factory=list)
    has_existing_loan: bool | None = None
    stated_need: str | None = None

    # Anything we computed rather than heard, so the trace stays honest.
    derived_fields: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    """Where a claim came from. Every rule that fires must produce one."""

    source_doc: str
    page_no: int
    heading: str = ""
    snippet: str


class RuleResult(BaseModel):
    """One eligibility condition, evaluated."""

    rule_id: str
    description: str
    passed: bool | None  # None = couldn't evaluate, field missing
    expected: str
    actual: str
    citation: Citation | None = None


class LadderStep(BaseModel):
    """One rung on the path from where you are to eligible."""

    order: int
    action: str
    unblocks_rule: str
    cost_rupees: float = 0.0
    time_days: int = 0
    where: str = ""
    detail: str = ""
    # The provision that makes this route real. A rung asserting a free 7-day
    # fix is only credible if it can point at the clause that grants it.
    citation: Citation | None = None


class Decision(BaseModel):
    """A scheme, evaluated against a profile. Produced by rules, never by the LLM."""

    scheme_id: str
    scheme_name: str
    status: EligibilityStatus

    rules: list[RuleResult] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)

    # Present when status is NOT_ELIGIBLE and a path exists.
    ladder: list[LadderStep] | None = None
    total_cost_rupees: float | None = None
    total_time_days: int | None = None

    benefit_summary: str = ""
    benefit_amount_rupees: float | None = None

    # Filled in by the LLM at the very end — language only, never logic.
    explanation: str = ""


class TrustTrace(BaseModel):
    """
    Replayable record of one decision.

    Same input must produce a byte-identical trace. That property is the whole
    audit story, so nothing non-deterministic (timestamps, ids) belongs in the
    hashed portion.
    """

    query_id: str
    profile: Profile
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    engine_version: str = "0.1.0"
    schemes_version: str = ""

    def fingerprint(self) -> str:
        import hashlib
        import json

        payload = json.dumps(
            {
                "profile": self.profile.model_dump(exclude={"raw_text"}),
                "decisions": [d.model_dump(exclude={"explanation"}) for d in self.decisions],
                "engine_version": self.engine_version,
                "schemes_version": self.schemes_version,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class RetrievedChunk(BaseModel):
    """A hit from the vector store, with everything needed to cite it."""

    chunk_id: str
    text: str
    source_doc: str
    scheme_id: str
    scheme_name: str
    page_no: int
    heading: str = ""
    distance: float = 0.0


class QueryRequest(BaseModel):
    text: str
    language: str = "hi"
    user_id: str = "demo"


class QueryResponse(BaseModel):
    """Everything the dashboard needs to show the full chain."""

    query_id: str
    profile: Profile
    missing_fields: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    trace_fingerprint: str = ""
    timings_ms: dict[str, float] = Field(default_factory=dict)
    debug: dict[str, Any] = Field(default_factory=dict)
