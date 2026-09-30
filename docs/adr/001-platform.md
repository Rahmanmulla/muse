# ADR-001 — Platform target for STIP v3

Date: 2026-09-30
Status: Accepted

## Context
- v1 spec (§6) said mobile-first (Android/iOS), web/desktop as extensions.
- v3 spec never names a platform.
- A verified working app already exists: React+TS web frontend + FastAPI backend.

## Decision
Build v3 as **web-first, evolving the existing app**. No native mobile rewrite.
Rationale (v3 §1): "Do not replace working systems merely because a different
approach looks cleaner. Prefer incremental architecture when the existing
foundation is sound."

## Consequences
- Performance budgets, haptics, and push are interpreted for web (v3's mobile
  wording applies where transferable; device-specific items are deferred).
- Native mobile (React Native / equivalent) is explicitly deferred, not ruled out.
- The API stays client-agnostic so a future mobile client can reuse it.
