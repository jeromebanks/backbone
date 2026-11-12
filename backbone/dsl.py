"""Fluent Python front-end for the query DSL. It only builds a `QueryPlan`, the same validated object the LLM
emits, so both paths share identical semantics, validation, SQL and results.

    from backbone.dsl import care
    q = (care.for_patient("HG-M042").during("2026-01-05", "2026-01-30")
             .include_excluded().care(group_by="week").compliance(consecutive_below=2))
    print(q.explain())
    results = q.execute(conn)
    print(q.to_sql(conn))
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from .query import CareStep, CompareStep, ComplianceStep, QueryPlan, Scope, TimelineStep, execute_plan


@dataclass(frozen=True)
class Query:
    _patients: object = "all"
    _start: str | None = None
    _end: str | None = None
    _types: tuple | None = None
    _excluded: bool = False
    _evidence: bool = True
    _steps: tuple = field(default_factory=tuple)

    # ---- scope builders (return new immutable queries)
    def for_patient(self, *mrns: str) -> "Query":
        return replace(self, _patients=list(mrns))

    def all_patients(self) -> "Query":
        return replace(self, _patients="all")

    def during(self, start: str | date, end: str | date) -> "Query":
        return replace(self, _start=str(start), _end=str(end))

    def on(self, day: str | date) -> "Query":
        return self.during(day, day)

    def of_types(self, *service_types: str) -> "Query":
        return replace(self, _types=tuple(service_types))

    def include_excluded(self, flag: bool = True) -> "Query":
        return replace(self, _excluded=flag)

    def without_evidence(self) -> "Query":
        return replace(self, _evidence=False)

    def _scope(self) -> Scope:
        if not (self._start and self._end):
            raise ValueError("call .during(start, end) or .on(day) before adding operations")
        return Scope(patients=self._patients, start=self._start, end=self._end,
                     service_types=list(self._types) if self._types else None,
                     include_excluded=self._excluded, include_evidence=self._evidence)

    # ---- operations (each captures the scope at the time it is added)
    def care(self, group_by: str = "none") -> "Query":
        return replace(self, _steps=self._steps + (CareStep(scope=self._scope(), group_by=group_by),))

    def compliance(self, consecutive_below: int | None = None) -> "Query":
        return replace(self, _steps=self._steps + (ComplianceStep(scope=self._scope(), consecutive_below=consecutive_below),))

    def timeline(self, *kinds: str, domains: list[str] | None = None) -> "Query":
        return replace(self, _steps=self._steps + (TimelineStep(scope=self._scope(), kinds=list(kinds),
                                                                observation_domains=domains),))

    def compare(self, split: str | date = "plan_change") -> "Query":
        return replace(self, _steps=self._steps + (CompareStep(scope=self._scope(), split=split),))

    # ---- terminals
    def plan(self, question: str = "(python DSL)") -> QueryPlan:
        return QueryPlan(question=question, steps=list(self._steps))

    def explain(self) -> str:
        return self.plan().explain()

    def execute(self, conn) -> dict:
        return execute_plan(conn, self.plan())

    def to_sql(self, conn) -> str:
        res = self.execute(conn)
        return "\n".join(f"-- {r['op']}\n" + "\n".join(f"{s['sql']};  -- params {s['params']}" for s in r["sql"])
                         for r in res["results"])


care = Query()
