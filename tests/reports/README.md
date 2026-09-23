# tests/reports

Evidence-driven, per-feature test & QA reports for Q-FLARE.

> **Convention:** one report file per feature, named after the feature
> (`<FEATURE>.md`). Every feature's work should begin by copying
> `_TEMPLATE.md` into `<FEATURE>.md` and filling in the before-state, then the
> after-state once implemented. Reports are honest by construction: they record
> the baseline, the problem, the resolution, and the verified result — never
> fabricated pass rates.

## Report index

| Report | Feature | Status |
| --- | --- | --- |
| [AI_ANALYTICS.md](./AI_ANALYTICS.md) | AI Analytics Dashboard (frontend/backend/ai-service/database/data/tests) | COMPLETE-PARTIAL — remaining items listed in report |
| | *(future features should use `_TEMPLATE.md`)* | |

## How to add a report

1. Copy `./_TEMPLATE.md` to `./<FEATURE>.md`.
2. Fill the **Before** section from the QA audit of that feature (or the
   current state if auditing first).
3. Implement the fixes; record each in **Changes / Problems & resolutions**.
4. Run the module test suites and record exact PASS/FAIL counts in
   **Verification**.
5. Mark every checkbox and set the final **Status**. Do not clear remaining
   items without actually fixing them.