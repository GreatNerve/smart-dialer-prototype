# 08 — Data Model

## Entities (logical DDL)

```sql
CREATE TABLE campaigns (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  pacing_mode TEXT NOT NULL DEFAULT 'auto', -- progressive|predictive|auto
  force_progressive BOOLEAN NOT NULL DEFAULT FALSE,
  target_abandon_prob DOUBLE PRECISION NOT NULL DEFAULT 0.03,
  abandon_rate_ceiling DOUBLE PRECISION NOT NULL DEFAULT 0.03,
  max_cps DOUBLE PRECISION NOT NULL DEFAULT 20,
  slew_factor DOUBLE PRECISION NOT NULL DEFAULT 0.5,
  overdial_allowance INT NOT NULL DEFAULT 0,
  min_warmup_samples INT NOT NULL DEFAULT 30,
  provider_name TEXT NOT NULL DEFAULT 'mock_a',
  time_scale DOUBLE PRECISION NOT NULL DEFAULT 60,
  status TEXT NOT NULL DEFAULT 'idle',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agents (
  id UUID PRIMARY KEY,
  campaign_id UUID REFERENCES campaigns(id),
  external_ref TEXT NOT NULL,
  state TEXT NOT NULL,
  version INT NOT NULL DEFAULT 0,
  locked_by TEXT,
  lease_expires_at TIMESTAMPTZ,
  reserved_call_id UUID,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agents_avail_idx ON agents (campaign_id, state) WHERE state = 'AVAILABLE';

CREATE TABLE campaign_contacts (
  id UUID PRIMARY KEY,
  campaign_id UUID REFERENCES campaigns(id),
  phone TEXT NOT NULL,
  priority INT NOT NULL DEFAULT 0,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  next_eligible_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  dnc BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL DEFAULT 'eligible', -- eligible|in_progress|done|exhausted
  version INT NOT NULL DEFAULT 0,
  last_call_id UUID
);
CREATE INDEX contacts_claim_idx ON campaign_contacts (campaign_id, status, next_eligible_at, priority);

CREATE TABLE calls (
  id UUID PRIMARY KEY,
  campaign_id UUID NOT NULL,
  agent_id UUID,
  contact_id UUID,
  provider_name TEXT,
  provider_call_id TEXT,
  idempotency_key TEXT UNIQUE,
  state TEXT NOT NULL,
  version INT NOT NULL DEFAULT 0,
  decision_id UUID,
  worker_id TEXT,
  lease_expires_at TIMESTAMPTZ,
  queued_at TIMESTAMPTZ,
  reserved_at TIMESTAMPTZ,
  initiated_at TIMESTAMPTZ,
  ringing_at TIMESTAMPTZ,
  answered_at TIMESTAMPTZ,
  connected_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  fail_reason TEXT
);
CREATE INDEX calls_campaign_state_idx ON calls (campaign_id, state);

CREATE TABLE call_jobs (
  id UUID PRIMARY KEY,
  campaign_id UUID NOT NULL,
  decision_id UUID NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  locked_by TEXT,
  lease_expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX call_jobs_pending_idx ON call_jobs (campaign_id, status, id);

CREATE TABLE provider_events (
  id UUID PRIMARY KEY,
  provider TEXT NOT NULL,
  provider_event_id TEXT NOT NULL,
  provider_call_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  out_of_order BOOLEAN NOT NULL DEFAULT FALSE,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_event_id)
);

CREATE TABLE safety_decisions (
  id UUID PRIMARY KEY, -- decision_id
  campaign_id UUID NOT NULL,
  desired_count INT NOT NULL,
  approved_count INT NOT NULL,
  outcome TEXT NOT NULL,
  mode TEXT NOT NULL,
  reason_codes JSONB NOT NULL,
  inputs JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE pacing_metrics (
  campaign_id UUID PRIMARY KEY,
  answer_rate_ewma DOUBLE PRECISION NOT NULL DEFAULT 0.3,
  setup_sec_ewma DOUBLE PRECISION NOT NULL DEFAULT 15,
  talk_sec_ewma DOUBLE PRECISION NOT NULL DEFAULT 120,
  samples INT NOT NULL DEFAULT 0,
  aggressiveness DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  last_approved INT NOT NULL DEFAULT 0,
  abandons_window INT NOT NULL DEFAULT 0,
  answered_window INT NOT NULL DEFAULT 0,
  window_started_at TIMESTAMPTZ
);

CREATE TABLE provider_health (
  provider_name TEXT PRIMARY KEY,
  error_rate_ewma DOUBLE PRECISION NOT NULL DEFAULT 0,
  p95_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
  circuit_open_until TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Tortoise models

Mirror the above under `backend/app/domain/models.py`. Native Tortoise migrations; use `RunSQL` for partial indexes if needed.
