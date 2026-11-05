"""Core data models for AgentGate."""

from __future__ import annotations

import math
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
        if not math.isfinite(self.amount):
            raise ValueError("Transaction amount must be a finite number")
        if self.amount < 0:
            raise ValueError("Transaction amount cannot be negative")
        if not self.currency:
            raise ValueError("Currency is required")
        if not self.merchant:
            raise ValueError("Merchant is required")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Transaction timestamp must be timezone-aware")


def _validate_amount(name: str, value: Any, allow_none: bool = True) -> None:
    """Require a finite, non-negative real number (or None when allowed).

    Strings, including numeric ones such as "200", are rejected rather than
    coerced, so a quoted YAML value fails at load time instead of mid-check.
    """
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be a number, got {type(value).__name__} {value!r}"
        )
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} cannot be negative, got {value!r}")


def _validate_count(name: str, value: Any) -> None:
    """Require a non-negative integer or None."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{name} must be an integer, got {type(value).__name__} {value!r}"
        )
    if value < 0:
        raise ValueError(f"{name} cannot be negative, got {value!r}")


@dataclass
class PolicyLimits:
    """Spending limits."""

    per_transaction: float | None = None
    daily: float | None = None
    weekly: float | None = None
    monthly: float | None = None
    currency: str = "USD"

    def __post_init__(self):
        for name in ("per_transaction", "daily", "weekly", "monthly"):
            _validate_amount(f"limits.{name}", getattr(self, name))
        if not isinstance(self.currency, str) or not self.currency:
            raise ValueError("limits.currency must be a non-empty string")


def normalize_category(category: str) -> str:
    """Canonical form used to compare categories: stripped and lower-cased."""
    return str(category).strip().lower()


def normalize_merchant(merchant: str) -> str:
    """Canonical form used to compare merchants: stripped and lower-cased."""
    return str(merchant).strip().lower()


@dataclass
class MerchantRules:
    """Merchant/category allow/block rules."""

    allowed_categories: list[str] | None = None  # None = all allowed
    blocked_categories: list[str] = field(default_factory=list)
    allowed_merchants: list[str] | None = None  # None = all allowed
    blocked_merchants: list[str] = field(default_factory=list)

    def __post_init__(self):
        # Category matching is case-insensitive, like merchant matching:
        # store categories lower-cased and compare against the lower-cased
        # transaction category.
        if self.allowed_categories is not None:
            self.allowed_categories = [normalize_category(c) for c in self.allowed_categories]
        self.blocked_categories = [normalize_category(c) for c in self.blocked_categories]


@dataclass
class VelocityRules:
    """Rate limiting for transactions."""

    max_per_hour: int | None = None
    max_per_day: int | None = None
    cooldown_seconds: float = 0

    def __post_init__(self):
        _validate_count("velocity.max_per_hour", self.max_per_hour)
        _validate_count("velocity.max_per_day", self.max_per_day)
        _validate_amount("velocity.cooldown_seconds", self.cooldown_seconds, allow_none=False)


@dataclass
class EscalationRules:
    """When to escalate to a human."""

    above_amount: float | None = None
    on_new_merchant: bool = False
    on_new_category: bool = False
    on_cumulative_above: float | None = None  # escalate when session total exceeds

    def __post_init__(self):
        _validate_amount("escalation.above_amount", self.above_amount)
        _validate_amount("escalation.on_cumulative_above", self.on_cumulative_above)


@dataclass
class TimeRestrictions:
    """When the agent is allowed to transact."""

    allowed_hours: tuple[int, int] | None = None  # (start, end) in 24h
    allowed_days: list[int] | None = None  # 0=Mon, 6=Sun

    def __post_init__(self):
        if self.allowed_hours is not None:
            hours = self.allowed_hours
            if isinstance(hours, (str, bytes)) or not isinstance(hours, (tuple, list)) or len(hours) != 2:
                raise ValueError(
                    f"time_restrictions.allowed_hours must be two integers [start, end], got {hours!r}"
                )
            for h in hours:
                if isinstance(h, bool) or not isinstance(h, int) or not 0 <= h <= 24:
                    raise ValueError(
                        f"time_restrictions.allowed_hours values must be integers in 0..24, got {hours!r}"
                    )
            self.allowed_hours = (hours[0], hours[1])
        if self.allowed_days is not None:
            days = self.allowed_days
            if isinstance(days, (str, bytes)) or not isinstance(days, (list, tuple)):
                raise ValueError(
                    f"time_restrictions.allowed_days must be a list of integers 0..6, got {days!r}"
                )
            for d in days:
                if isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6:
                    raise ValueError(
                        f"time_restrictions.allowed_days values must be integers in 0..6, got {days!r}"
                    )


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
    # For escalated transactions resolved by an escalation handler:
    # "approved" or "rejected". None when no handler was consulted.
    escalation_outcome: str | None = None
    id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:12]}")
