# tests

Cross-module integration and contract tests for Q-FLARE.

> **Status:** placeholder.

## Planned scope

- Contract tests validating that `ai-service` responses match
  `frontend/src/types/ai.ts`.
- End-to-end: frontend ✓ ai-service ✓ quantum-service flows.

Module-local tests live with each module (e.g. `ai-service` runs `npm test`
using `node:test`).