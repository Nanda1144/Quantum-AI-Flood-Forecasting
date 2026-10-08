# Quantum / AI Integration

**Owner:** forecasting module (integration boundary documentation only)
**Documents:** [`quantum-integration.md`](quantum-integration.md), `quantum-integration.mmd`

---

## Purpose

Documents the **intended** connection between the forecast output and the team's
optimization / quantum layer, and states plainly what is not yet connected.

## Status legend

`[EXISTING]` · `[MY IMPLEMENTATION]` · `[TEAM IMPLEMENTATION]` · `[PROPOSED INTEGRATION]` ·
`[NOT CURRENTLY AVAILABLE]`

## The three sentences that matter

1. **The forecasting module owns the forecast side of this boundary. The team owns the optimization and
   quantum side. Navya does not modify optimization, QUBO, or quantum code.**
2. **No quantum advantage, quantum speedup, or performance superiority is claimed, implied, or
   estimated anywhere in this work.**
3. **No quantum result has been produced or measured by Navya.** Any comparison of classical
   against quantum solving is a team-owned activity requiring real measurement on real
   workloads with real instances.
