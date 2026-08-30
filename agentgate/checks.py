"""Individual policy checks. Each is a pure function: transaction + policy + ledger → Check."""

from __future__ import annotations

import fnmatch
from datetime import datetime, timedelta, timezone

from .ledger import InMemoryLedger
from .models import Check, CheckResult, Policy, Transaction


def check_amount_limit(tx: Transaction, policy: Policy, **_) -> Check:
    """Check if transaction amount exceeds per-transaction limit."""
    limit = policy.limits.per_transaction
    if limit is None:
        return Check("amount_limit", CheckResult.SKIP, "No per-transaction limit set")
    if tx.amount > limit:
        return Check(
            "amount_limit",
            CheckResult.FAIL,
            f"Amount {tx.amount} exceeds limit {limit}",
            {"amount": tx.amount, "limit": limit},
        )
    return Check("amount_limit", CheckResult.PASS, f"Amount {tx.amount} within limit {limit}")


def check_daily_limit(tx: Transaction, policy: Policy, ledger: InMemoryLedger, **_) -> Check:
    """Check if transaction would exceed daily spending limit."""
    limit = policy.limits.daily
    if limit is None:
        return Check("daily_limit", CheckResult.SKIP, "No daily limit set")
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    spent = ledger.total_since(tx.agent_id, start_of_day)
    if spent + tx.amount > limit:
        return Check(
            "daily_limit",
            CheckResult.FAIL,
            f"Daily total {spent + tx.amount:.2f} would exceed limit {limit}",
            {"spent_today": spent, "proposed": tx.amount, "limit": limit},
        )
    return Check("daily_limit", CheckResult.PASS, f"Daily spend OK ({spent + tx.amount:.2f}/{limit})")


def check_weekly_limit(tx: Transaction, policy: Policy, ledger: InMemoryLedger, **_) -> Check:
    """Check if transaction would exceed weekly spending limit."""
    limit = policy.limits.weekly
    if limit is None:
        return Check("weekly_limit", CheckResult.SKIP, "No weekly limit set")
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    spent = ledger.total_since(tx.agent_id, week_start)
    if spent + tx.amount > limit:
        return Check(
            "weekly_limit",
            CheckResult.FAIL,
            f"Weekly total {spent + tx.amount:.2f} would exceed limit {limit}",
            {"spent_this_week": spent, "proposed": tx.amount, "limit": limit},
        )
    return Check("weekly_limit", CheckResult.PASS, f"Weekly spend OK ({spent + tx.amount:.2f}/{limit})")


def check_monthly_limit(tx: Transaction, policy: Policy, ledger: InMemoryLedger, **_) -> Check:
    """Check if transaction would exceed monthly spending limit."""
    limit = policy.limits.monthly
    if limit is None:
        return Check("monthly_limit", CheckResult.SKIP, "No monthly limit set")
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = ledger.total_since(tx.agent_id, month_start)
    if spent + tx.amount > limit:
        return Check(
            "monthly_limit",
            CheckResult.FAIL,
            f"Monthly total {spent + tx.amount:.2f} would exceed limit {limit}",
            {"spent_this_month": spent, "proposed": tx.amount, "limit": limit},
        )
    return Check("monthly_limit", CheckResult.PASS, f"Monthly spend OK ({spent + tx.amount:.2f}/{limit})")


def check_category(tx: Transaction, policy: Policy, **_) -> Check:
    """Check if transaction category is allowed."""
    rules = policy.merchants

    # Check blocked categories first
    if tx.category in rules.blocked_categories:
        return Check(
            "category",
            CheckResult.FAIL,
            f"Category '{tx.category}' is blocked",
            {"category": tx.category, "blocked": rules.blocked_categories},
        )

    # If allowlist is set, category must be in it
    if rules.allowed_categories is not None and tx.category not in rules.allowed_categories:
        return Check(
            "category",
            CheckResult.FAIL,
            f"Category '{tx.category}' not in allowed list",
            {"category": tx.category, "allowed": rules.allowed_categories},
        )

    return Check("category", CheckResult.PASS, f"Category '{tx.category}' is allowed")


def check_merchant(tx: Transaction, policy: Policy, **_) -> Check:
    """Check if merchant is allowed."""
    rules = policy.merchants

    # Check blocked merchants (supports glob patterns)
    for pattern in rules.blocked_merchants:
        if fnmatch.fnmatch(tx.merchant.lower(), pattern.lower()):
            return Check(
                "merchant",
                CheckResult.FAIL,
                f"Merchant '{tx.merchant}' matches blocked pattern '{pattern}'",
                {"merchant": tx.merchant, "pattern": pattern},
            )

    # If allowlist is set, merchant must be in it
    if rules.allowed_merchants is not None:
        matched = any(
            fnmatch.fnmatch(tx.merchant.lower(), p.lower())
            for p in rules.allowed_merchants
        )
        if not matched:
            return Check(
                "merchant",
                CheckResult.FAIL,
                f"Merchant '{tx.merchant}' not in allowed list",
                {"merchant": tx.merchant, "allowed": rules.allowed_merchants},
            )

    return Check("merchant", CheckResult.PASS, f"Merchant '{tx.merchant}' is allowed")


def check_velocity(tx: Transaction, policy: Policy, ledger: InMemoryLedger, **_) -> Check:
    """Check transaction velocity (rate limiting)."""
    rules = policy.velocity
    now = datetime.now(timezone.utc)
    failures = []

    # Cooldown check
    if rules.cooldown_seconds > 0:
        last_time = ledger.last_transaction_time(tx.agent_id)
        if last_time:
            elapsed = (now - last_time).total_seconds()
            if elapsed < rules.cooldown_seconds:
                failures.append(
                    f"Cooldown: {elapsed:.1f}s since last tx, need {rules.cooldown_seconds}s"
                )

    # Hourly rate check
    if rules.max_per_hour is not None:
        hour_ago = now - timedelta(hours=1)
        count = ledger.count_since(tx.agent_id, hour_ago)
        if count >= rules.max_per_hour:
            failures.append(f"Hourly limit: {count} txns in last hour (max {rules.max_per_hour})")

    # Daily rate check
    if rules.max_per_day is not None:
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        count = ledger.count_since(tx.agent_id, start_of_day)
        if count >= rules.max_per_day:
            failures.append(f"Daily limit: {count} txns today (max {rules.max_per_day})")

    if failures:
        return Check(
            "velocity",
            CheckResult.FAIL,
            "; ".join(failures),
            {"failures": failures},
        )

    return Check("velocity", CheckResult.PASS, "Velocity checks passed")


def check_time_restrictions(tx: Transaction, policy: Policy, **_) -> Check:
    """Check if current time is within allowed transaction window."""
    rules = policy.time_restrictions
    now = datetime.now(timezone.utc)

    if rules.allowed_days is not None:
        if now.weekday() not in rules.allowed_days:
            return Check(
                "time_restriction",
                CheckResult.FAIL,
                f"Day {now.strftime('%A')} not in allowed days",
                {"day": now.weekday(), "allowed": rules.allowed_days},
            )

    if rules.allowed_hours is not None:
        start, end = rules.allowed_hours
        if not (start <= now.hour < end):
            return Check(
                "time_restriction",
                CheckResult.FAIL,
                f"Hour {now.hour} outside allowed range {start}-{end}",
                {"hour": now.hour, "allowed_start": start, "allowed_end": end},
            )

    return Check("time_restriction", CheckResult.PASS, "Within allowed time window")


def check_escalation(tx: Transaction, policy: Policy, ledger: InMemoryLedger, **_) -> Check:
    """Check if transaction should be escalated to a human.
    
    Unlike other checks, FAIL here means ESCALATE, not DENY.
    """
    rules = policy.escalation
    reasons = []

    if rules.above_amount is not None and tx.amount > rules.above_amount:
        reasons.append(f"Amount {tx.amount} exceeds escalation threshold {rules.above_amount}")

    if rules.on_new_merchant:
        known = ledger.get_known_merchants(tx.agent_id)
        if tx.merchant not in known and known:  # don't escalate the very first tx
            reasons.append(f"New merchant: {tx.merchant}")

    if rules.on_new_category:
        known = ledger.get_known_categories(tx.agent_id)
        if tx.category not in known and known:
            reasons.append(f"New category: {tx.category}")

    if rules.on_cumulative_above is not None:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        total = ledger.total_since(tx.agent_id, start_of_day) + tx.amount
        if total > rules.on_cumulative_above:
            reasons.append(f"Cumulative total {total:.2f} exceeds escalation threshold {rules.on_cumulative_above}")

    if reasons:
        return Check(
            "escalation",
            CheckResult.FAIL,
            "; ".join(reasons),
            {"reasons": reasons},
        )

    return Check("escalation", CheckResult.PASS, "No escalation needed")


# Registry of all checks in evaluation order.
# Escalation is last because it only matters if everything else passes.
ALL_CHECKS = [
    check_amount_limit,
    check_daily_limit,
    check_weekly_limit,
    check_monthly_limit,
    check_category,
    check_merchant,
    check_velocity,
    check_time_restrictions,
    check_escalation,
]
