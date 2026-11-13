# Agent reference docs

Start with [`/AGENTS.md`](../../AGENTS.md) (invariants, commands, confidentiality). These files go deeper.

| File | Read when you are… |
|---|---|
| [HANDOFF.md](HANDOFF.md) | **starting a new session**: what changed in the #1–#75 fixes, pending rebuilds and regenerations, open issues, what costs money, user preferences |
| [ARCHITECTURE.md](ARCHITECTURE.md) | orienting: layers, tables, modules, data flow, the results envelope |
| [EXTRACTION.md](EXTRACTION.md) | changing what the LLM extracts, the prompt, the cache or the LLM backends |
| [RECONCILIATION.md](RECONCILIATION.md) | changing how claims become encounters, minutes, eligibility, plans or assessments |
| [QUERY_DSL.md](QUERY_DSL.md) | adding or changing operators, QueryPlan fields, the planner/narrator, or the fluent DSL |
| [VERIFICATION.md](VERIFICATION.md) | testing: golden values, fixtures, verify-answers, benchmarks, ablation |
| [DECISIONS.md](DECISIONS.md) | about to propose a design change (what was chosen, rejected, and why) |
| [RUNBOOK.md](RUNBOOK.md) | preparing for or running the live review session with Backbone |
| [../INGESTION_PIPELINE.md](../INGESTION_PIPELINE.md) | designing or building production ingestion: stages, idempotency keys, lanes, coalescing, backfills |
| [../CLINICAL_QA_DESIGN.md](../CLINICAL_QA_DESIGN.md) | building natural-language Q&A for clinicians at scale; the DSL roadmap |
| [../../.claude/skills/clinical-qa/SKILL.md](../../.claude/skills/clinical-qa/SKILL.md) | answering a clinical question yourself in this repo (agent workflow) |
| [../AI_USAGE.md](../AI_USAGE.md) | anything touching LLM calls: where AI is used vs deterministic, model choice, costs, risks |
| [../ROADMAP.md](../ROADMAP.md) | planning production work: target design, tech stack, scalability choke points, phases |
