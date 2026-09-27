# API Integration

**Owner:** Navya
**Documents:** [`api-integration.md`](api-integration.md), `api-integration.mmd`

---

## Purpose

Documents the Navya forecast contract on both sides of the stack, and draws a hard line
between what Navya owns and what the team owns.

## The one-line rule

> **Navya owns the forecast contract. The team owns the HTTP surface, the routes, and the
> persisted schema. Navya does not modify team-owned API files to support this contract.**

## Status legend

`[EXISTING]` · `[MY IMPLEMENTATION]` · `[TEAM IMPLEMENTATION]` · `[PROPOSED INTEGRATION]` ·
`[NOT CURRENTLY AVAILABLE]`

## The integration statement

> **Existing optimization currently requires forecast_id. Additional forecast-derived risk
> fields require team-owner integration.**
