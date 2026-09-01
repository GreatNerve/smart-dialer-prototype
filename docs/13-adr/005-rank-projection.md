# ADR-005: Rank-monotonic call projection

## Status

Accepted

## Context

Providers duplicate and reorder events; workers crash mid-handler.

## Decision

Append-only `provider_events` with unique event ids; call state moves only to higher rank; terminals absorbing.

## Consequences

- Explains COMPLETED-before-RINGING safely.
- Cannot “repair” by regressing state; compensation via new terminal reasons if needed.
