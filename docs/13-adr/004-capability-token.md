# ADR-004: Capability-token Safety boundary

## Status

Accepted

## Context

“Predictive must not switch safety off.” Convention-only guards are erasable.

## Decision

Pacing emits `DialRequest` only. `SafetyController.evaluate` alone constructs frozen `ApprovedDialBatch`. Allocator accepts only that type. Import boundary test.

## Consequences

- Bypass requires editing Safety or breaking types/tests.
- Slight ceremony vs free-form int “how many to dial.”
