# ADR-003 — E2EE: architecture-ready, not in MVP

Date: 2026-09-30
Status: Accepted

## Context
Both specs demand E2EE ("server should not receive plaintext", no backdoors),
but v3's own MVP (§98) omits it; post-MVP only mentions multi-device
encryption. Implementing E2EE now (Signal-style sessions, key rotation,
multi-device provisioning) is the largest single scope item and would
destabilize the verified messaging core.

## Decision
Ship v3-MVP **without E2EE**, with a documented upgrade path:
- Transport is TLS; authorization is server-side and strict (no trust in client).
- Message schema keeps a nullable `ciphertext` envelope field reserved so a
  future protocol can ride the same tables without migration pain.
- Search stays server-side for now; §55's local-index design is the documented
  target under E2EE.
- Moderation/reporting never gets a plaintext backdoor (v3 §47).
- The API and docs state plaintext-server honestly; no "encrypted" claims.

## Consequences
- A future E2EE rollout needs: device key provisioning, session establishment,
  key rotation, and the recovery story from ADR-002. This ADR is its starting point.
- If threat-model requirements change, this decision gets revisited first.
