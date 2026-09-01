# ADR-007: Compressed simulation time

## Status

Accepted

## Context

Talk times of 90–180s make demos unusable in real time.

## Decision

Real wall clock for leases/DB; divide mock call phase durations by `time_scale`. Inject `Clock` port in tests.

## Consequences

- Honest lease expiry behaviour.
- Must document that metrics “seconds” are simulated-logical where noted.
