# ADR-002: No message broker

## Status

Accepted

## Context

Brief discourages impressive-looking unnecessary infra. Workers must share a campaign.

## Decision

`call_jobs` table + SKIP LOCKED replaces Kafka/RabbitMQ for this prototype.

## Consequences

- Easy local run (compose: postgres + app).
- At very high job rates, table churn becomes a bottleneck (see scale doc).
