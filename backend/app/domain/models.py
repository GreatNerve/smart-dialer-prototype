from __future__ import annotations

from tortoise import fields, models


class Campaign(models.Model):
    id = fields.UUIDField(pk=True)
    name = fields.CharField(max_length=200)
    pacing_mode = fields.CharField(max_length=32, default="auto")
    force_progressive = fields.BooleanField(default=False)
    target_abandon_prob = fields.FloatField(default=0.03)
    abandon_rate_ceiling = fields.FloatField(default=0.03)
    max_cps = fields.FloatField(default=20.0)
    slew_factor = fields.FloatField(default=0.5)
    overdial_allowance = fields.IntField(default=0)
    min_warmup_samples = fields.IntField(default=30)
    provider_name = fields.CharField(max_length=64, default="mock_a")
    time_scale = fields.FloatField(default=60.0)
    status = fields.CharField(max_length=32, default="idle")
    answer_rate_sim = fields.FloatField(default=0.5)
    talk_sec_sim = fields.FloatField(default=90.0)
    window_start_hour = fields.IntField(default=0)
    window_end_hour = fields.IntField(default=24)
    wrap_up_seconds = fields.FloatField(default=8.0)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "campaigns"


class Agent(models.Model):
    id = fields.UUIDField(pk=True)
    campaign = fields.ForeignKeyField("models.Campaign", related_name="agents")
    external_ref = fields.CharField(max_length=128)
    state = fields.CharField(max_length=32)
    version = fields.IntField(default=0)
    locked_by = fields.CharField(max_length=128, null=True)
    lease_expires_at = fields.DatetimeField(null=True)
    reserved_call_id = fields.UUIDField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "agents"


class CampaignContact(models.Model):
    id = fields.UUIDField(pk=True)
    campaign = fields.ForeignKeyField("models.Campaign", related_name="contacts")
    phone = fields.CharField(max_length=32)
    priority = fields.IntField(default=0)
    attempts = fields.IntField(default=0)
    max_attempts = fields.IntField(default=3)
    next_eligible_at = fields.DatetimeField(auto_now_add=True)
    dnc = fields.BooleanField(default=False)
    status = fields.CharField(max_length=32, default="eligible")
    version = fields.IntField(default=0)
    last_call_id = fields.UUIDField(null=True)

    class Meta:
        table = "campaign_contacts"


class Call(models.Model):
    id = fields.UUIDField(pk=True)
    campaign = fields.ForeignKeyField("models.Campaign", related_name="calls")
    agent = fields.ForeignKeyField("models.Agent", related_name="calls", null=True)
    contact = fields.ForeignKeyField("models.CampaignContact", related_name="calls", null=True)
    provider_name = fields.CharField(max_length=64, null=True)
    provider_call_id = fields.CharField(max_length=128, null=True)
    idempotency_key = fields.CharField(max_length=128, unique=True, null=True)
    state = fields.CharField(max_length=32)
    version = fields.IntField(default=0)
    decision_id = fields.UUIDField(null=True)
    worker_id = fields.CharField(max_length=128, null=True)
    lease_expires_at = fields.DatetimeField(null=True)
    queued_at = fields.DatetimeField(null=True)
    reserved_at = fields.DatetimeField(null=True)
    initiated_at = fields.DatetimeField(null=True)
    ringing_at = fields.DatetimeField(null=True)
    answered_at = fields.DatetimeField(null=True)
    connected_at = fields.DatetimeField(null=True)
    ended_at = fields.DatetimeField(null=True)
    fail_reason = fields.CharField(max_length=256, null=True)

    class Meta:
        table = "calls"


class CallJob(models.Model):
    id = fields.UUIDField(pk=True)
    campaign = fields.ForeignKeyField("models.Campaign", related_name="jobs")
    decision_id = fields.UUIDField()
    status = fields.CharField(max_length=32, default="PENDING")
    locked_by = fields.CharField(max_length=128, null=True)
    lease_expires_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "call_jobs"


class ProviderEvent(models.Model):
    id = fields.UUIDField(pk=True)
    provider = fields.CharField(max_length=64)
    provider_event_id = fields.CharField(max_length=128)
    provider_call_id = fields.CharField(max_length=128)
    event_type = fields.CharField(max_length=64)
    payload = fields.JSONField()
    out_of_order = fields.BooleanField(default=False)
    received_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "provider_events"
        unique_together = (("provider", "provider_event_id"),)


class SafetyDecision(models.Model):
    id = fields.UUIDField(pk=True)
    campaign = fields.ForeignKeyField("models.Campaign", related_name="decisions")
    desired_count = fields.IntField()
    approved_count = fields.IntField()
    outcome = fields.CharField(max_length=32)
    mode = fields.CharField(max_length=32)
    reason_codes = fields.JSONField()
    inputs = fields.JSONField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "safety_decisions"


class PacingMetrics(models.Model):
    campaign = fields.OneToOneField("models.Campaign", pk=True, related_name="metrics")
    answer_rate_ewma = fields.FloatField(default=0.3)
    setup_sec_ewma = fields.FloatField(default=15.0)
    talk_sec_ewma = fields.FloatField(default=120.0)
    samples = fields.IntField(default=0)
    aggressiveness = fields.FloatField(default=1.0)
    last_approved = fields.IntField(default=0)
    abandons_window = fields.IntField(default=0)
    answered_window = fields.IntField(default=0)
    window_started_at = fields.DatetimeField(null=True)

    class Meta:
        table = "pacing_metrics"


class ProviderHealth(models.Model):
    provider_name = fields.CharField(max_length=64, pk=True)
    error_rate_ewma = fields.FloatField(default=0.0)
    p95_latency_ms = fields.FloatField(default=0.0)
    circuit_open_until = fields.DatetimeField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "provider_health"


class SystemFlag(models.Model):
    key = fields.CharField(max_length=64, pk=True)
    value = fields.CharField(max_length=256, default="")
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "system_flags"
