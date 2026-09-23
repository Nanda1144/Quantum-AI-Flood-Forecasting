# Test Report Template — <FEATURE>

> Fill every section. Remove the `<...>` placeholders. Keep the
> Before/After framing: the report is evidence of what changed and why.

## Feature

- **Name:** <Feature name>
- **Scope (module(s)):** <e.g. frontend / backend / ai-service / database / data / tests>
- **Owner:** Nanda
- **Date:** <YYYY-MM-DD>
- **Status:** COMPLETE | COMPLETE-PARTIAL | INCOMPLETE

## 1. Before (baseline / audit findings)

| Area | Finding | Severity |
| --- | --- | --- |
| ... | ... | high / medium / low |

## 2. Problems identified

1. **Problem:** <short title> — <details, with file:line references where relevant>
2. ...

## 3. What we did (resolution)

1. **Fix:** <what changed, file:line or file path>
   - Why: <rationale; no fabricated data, every fallback labelled>
2. ...

## 4. After (verified state)

| Area | Verification | Result |
| --- | --- | --- |
| ... | ... | PASS / FAIL |

## 5. Tests

| Suite | Before | After |
| --- | --- | --- |
| `ai-service` pytest | <N passed / N failed> | <N passed / N failed> |
| `backend` unit | ... | ... |
| `backend` integration | ... | ... |
| `frontend` vitest | ... | ... |

Commands used (exact):

```
<commands>
```

## 6. Build & lint

| Check | Command | Result |
| --- | --- | --- |
| build | ... | PASS / FAIL |
| lint / typecheck | ... | PASS / FAIL |

## 7. Remaining issues (not fixed, with reason)

- **<issue>** — left as-is because <reason / out of scope>. For the issue tracker.

## 8. Final verdict

**Status:** <COMPLETE | COMPLETE-PARTIAL | INCOMPLETE>

Summary: <2–3 sentences: what the feature now does truthfully, what is verified,
what remains. No invented metrics.