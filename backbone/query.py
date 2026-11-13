"""The query DSL: a typed, validated plan of domain operations.

A question becomes a QueryPlan (written by the LLM or by hand); Pydantic validates it; `execute_plan` runs it
with parameterized, read-only SQL over the reconciled abstraction. The LLM never writes SQL or code. Anything
the operators cannot express is reported through `unsupported_reason` instead of improvised.

    QueryPlan(question=..., steps=[
        CareStep(scope=Scope(patients=["HG-M042"], start="2026-01-05", end="2026-01-30"), group_by="week"),
        ComplianceStep(scope=..., consecutive_below=2),
    ])
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import ServiceType


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(Strict):
    """Reusable filter shared by every operator."""
    patients: Union[Literal["all"], list[str]] = Field(description='Patient MRNs, or "all" for collection-wide')
    start: date
    end: date
    service_types: Optional[list[ServiceType]] = Field(default=None, description="Restrict to these service types")
    include_excluded: bool = Field(default=False, description="Also return encounters that do not count (with reasons)")
    include_evidence: bool = Field(default=True, description="Attach source passages")

    @model_validator(mode="after")
    def _order(self):
        if self.end < self.start:
            raise ValueError("scope.end is before scope.start")
        return self


class CareStep(Strict):
    """Therapy sessions, distinct therapy days and patient-present minutes/hours (with bounds)."""
    op: Literal["care"] = "care"
    scope: Scope
    group_by: Literal["none", "service_type", "day", "week", "patient"] = "none"


COMPLIANCE_SERVICE_TYPES_REJECTED = (
    "compliance does not accept scope.service_types: each treatment-plan requirement counts the service types the "
    "plan states. Drop service_types, or use care with service_types for delivered totals.")


class ComplianceStep(Strict):
    """Per Mon–Sun week: treatment-plan goal in effect, delivered totals, MET / NOT_MET / UNDETERMINED.
    Its scope must not set service_types: each requirement counts the service types its plan states (#21, #47)."""
    op: Literal["compliance"] = "compliance"
    scope: Scope
    consecutive_below: Optional[int] = Field(default=None, ge=2, description="Also report runs of >= N consecutive weeks below goal")

    @model_validator(mode="after")
    def _no_service_types(self):
        if self.scope.service_types:
            raise ValueError(COMPLIANCE_SERVICE_TYPES_REJECTED)
        return self


class TimelineStep(Strict):
    """Chronological facts: encounters (with how each record was used), documents, reconciliation decisions,
    assessments, observations. A one-day scope reconstructs that day."""
    op: Literal["timeline"] = "timeline"
    scope: Scope
    kinds: list[Literal["encounters", "documents", "decisions", "assessments", "observations"]]
    observation_domains: Optional[list[Literal["mood", "sleep", "anxiety", "avoidance", "functioning", "safety",
                                                "engagement", "overall_progress", "other"]]] = None


class CompareStep(Strict):
    """Care before vs after a split date, or before vs after a treatment-plan change."""
    op: Literal["compare"] = "compare"
    scope: Scope
    split: Union[Literal["plan_change"], date]


Step = Annotated[Union[CareStep, ComplianceStep, TimelineStep, CompareStep], Field(discriminator="op")]


class QueryPlan(Strict):
    question: str
    steps: list[Step] = Field(description="One or more operations; results are returned per step")
    unsupported_reason: Optional[str] = Field(default=None, description="Set (with no steps) when the question cannot be answered with these operations")

    def explain(self) -> str:
        lines = [f"QueryPlan: {self.question}"]
        if self.unsupported_reason:
            lines.append(f"  UNSUPPORTED: {self.unsupported_reason}")
        for i, s in enumerate(self.steps, 1):
            sc = s.scope
            extra = {k: v for k, v in s.model_dump(exclude={"op", "scope"}).items() if v is not None}
            lines.append(f"  {i}. {s.op}(patients={sc.patients}, {sc.start}..{sc.end}"
                         + (f", types={sc.service_types}" if sc.service_types else "")
                         + (", include_excluded" if sc.include_excluded else "")
                         + "".join(f", {k}={v}" for k, v in extra.items()) + ")")
        return "\n".join(lines)


def execute_plan(conn, plan: QueryPlan) -> dict:
    from . import operators
    if plan.unsupported_reason and not plan.steps:
        return {"question": plan.question, "unsupported": plan.unsupported_reason, "results": []}
    fns = {"care": operators.care, "compliance": operators.compliance, "timeline": operators.timeline,
           "compare": operators.compare}
    cache: dict = {}        # corpus-wide lookups shared by this plan's steps (#57); it lives for this call only
    return {"question": plan.question, "plan": plan.model_dump(mode="json"),
            "results": [fns[s.op](conn, s, cache=cache) for s in plan.steps]}
