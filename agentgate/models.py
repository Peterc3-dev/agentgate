"""Core data models for AgentGate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Decision(str, Enum):
    """Result of a policy evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


class CheckResult(str, Enum):
    """Result of an individual policy check."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"  # check not applicable


@dataclass(frozen=True)
class Transaction:
    """A proposed agent-initiated transaction."""

    amount: float
    currency: str
    merchant: str
    category: str
    agent_id: str
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"tx_{uuid.uuid4().hex[:12]}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if self.amount < 0:
            raise ValueError("Transaction amount cannot be negative")
        if not self.currency:
            raise ValueError("Currency is required")
        if not self.merchant:
            raise ValueError("Merchant is required")


@dataclass
class PolicyLimits:
    """Spending limits."""

    per_transaction: float | None = None
    daily: float | None = None
    weekly: float | None = None
    monthly: float | None = None
    currency: str = "USD"


@dataclass
class MerchantRules:
    """Merchant/category allow/block rules."""

    allowed_categories: list[str] | None = None  # None = all allowed
    blocked_categories: list[str] = field(default_factory=list)
    allowed_merchants: list[str] | None = None  # None = all allowed
    blocked_merchants: list[str] = field(default_factory=list)


@dataclass
class VelocityRules:
    """Rate limiting for transactions."""

    max_per_hour: int | None = None
    max_per_day: int | None = None
    cooldown_seconds: float = 0


@dataclass
class EscalationRules:
    """When to escalate to a human."""

    above_amount: float | None = None
    on_new_merchant: bool = False
    on_new_category: bool = False
    on_cumulative_above: float | None = None  # escalate when session total exceeds


@dataclass
class TimeRestrictions:
    """When the agent is allowed to transact."""

    allowed_hours: tuple[int, int] | None = None  # (start, end) in 24h
    allowed_days: list[int] | None = None  # 0=Mon, 6=Sun


@dataclass
class Policy:
    """Complete policy definition for an agent."""

    name: str = "default"
    version: str = "1"
    limits: PolicyLimits = field(default_factory=PolicyLimits)
    merchants: MerchantRules = field(default_factory=MerchantRules)
    velocity: VelocityRules = field(default_factory=VelocityRules)
    escalation: EscalationRules = field(default_factory=EscalationRules)
    time_restrictions: TimeRestrictions = field(default_factory=TimeRestrictions)

    # Convenience constructor
    @classmethod
    def simple(
        cls,
        max_per_transaction: float = 50.0,
        max_daily: float = 200.0,
        max_monthly: float = 2000.0,
        allowed_categories: list[str] | None = None,
        blocked_merchants: list[str] | None = None,
        require_escalation_above: float | None = None,
    ) -> Policy:
        return cls(
            limits=PolicyLimits(
                per_transaction=max_per_transaction,
                daily=max_daily,
                monthly=max_monthly,
            ),
            merchants=MerchantRules(
                allowed_categories=allowed_categories,
                blocked_merchants=blocked_merchants or [],
            ),
            escalation=EscalationRules(above_amount=require_escalation_above),
        )


@dataclass
class Check:
    """Result of a single policy check."""

    name: str
    result: CheckResult
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """Full result of a gate evaluation."""

    decision: Decision
    transaction: Transaction
    checks: list[Check]
    escalation_reasons: list[str] = field(default_factory=list)
    audit: AuditEntry | None = None

    @property
    def passed(self) -> bool:
        return self.decision == Decision.ALLOW

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if c.result == CheckResult.FAIL]


@dataclass
class AuditEntry:
    """Immutable record of a gate decision."""

    timestamp: datetime
    transaction_id: str
    agent_id: str
    decision: Decision
    checks_passed: list[str]
    checks_failed: list[str]
    escalation_reasons: list[str]
    reasoning: str
    policy_name: str
    policy_version: str
    id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:12]}")
