# ADR-002 — Auth flow: v3 state machine

Date: 2026-09-30
Status: Accepted

## Context
v3 (§5, §8) mandates: email/phone → verify → username → password → display
name → identity → starter cosmetics → find people → first chat. Username is
never a login credential. The built app takes username+password up front.

## Decision
- New signups go through the v3 state machine (new endpoints; old
  `/auth/signup` kept working but deprecated).
- Existing accounts are grandfathered as identifier-verified (no forced
  re-verification, no lockouts).
- OTP goes through a pluggable `VerificationProvider` interface; the dev
  provider (in-band codes) ships now, a real SMS/email vendor plugs in later
  without API changes.
- Recovery (`/auth/recovery/*`) restores *access*; encrypted-history restore is
  N/A until E2EE (see ADR-003) and the API says so honestly.

## Username policy (v3 §6; numbers chosen, documented)
- 3–20 chars, `[a-z0-9_]`, NFKC-normalized, case-insensitive uniqueness.
- Reserved: admin, support, stip, system, official, staff, help, security + lookalikes.
- Change cooldown: 30 days. Released names held 30 days before reuse.

## Consequences
- Migration is additive (new tables/columns, no destructive changes).
- Stricter vendors/policies can tighten numbers later without breaking the flow.
