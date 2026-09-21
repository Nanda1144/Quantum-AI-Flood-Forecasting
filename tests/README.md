# tests

Cross-module integration, contract, and QA reports for Q-FLARE.

> **Status:** active for AI Analytics; per-feature reports continue for the
> remaining features.

## Reports

Per-feature before/after test reports (baseline → problem → resolution →
verified result) live in [`reports/`](./reports/), one file per feature, using
[`reports/_TEMPLATE.md`](./reports/_TEMPLATE.md):

- [AI Analytics Dashboard](./reports/AI_ANALYTICS.md) — COMPLETE-PARTIAL

## Planned scope

- Contract tests validating that `ai-service` responses match
  `frontend/src/types/ai.ts` (started in `ai-service/tests/test_contract.py`).
- End-to-end: frontend ✓ ai-service ✓ quantum-service flows.

Module-local tests live with each module (e.g. `backend` and `frontend` run
vitest, `ai-service` runs pytest).