"""Tests for AgentGate core functionality."""

import pytest
from agentgate import (
    Decision,
    EscalationRules,
    Gate,
    GatedTransactionDenied,
    GatedTransactionEscalated,
    MerchantRules,
    Policy,
    PolicyLimits,
    TimeRestrictions,
    Transaction,
    VelocityRules,
    gated,
)


def make_tx(**overrides):
    defaults = dict(
        amount=25.0,
        currency="USD",
        merchant="staples.com",
        category="office_supplies",
        agent_id="test-agent",
        reasoning="Test purchase",
    )
    defaults.update(overrides)
    return Transaction(**defaults)


# --- Amount Limits ---


def test_allow_within_limit():
    policy = Policy(limits=PolicyLimits(per_transaction=50.0))
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(amount=25.0))
    assert result.decision == Decision.ALLOW


def test_deny_over_limit():
    policy = Policy(limits=PolicyLimits(per_transaction=50.0))
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(amount=75.0))
    assert result.decision == Decision.DENY
    assert any(c.name == "amount_limit" for c in result.failed_checks)


def test_no_limit_allows_any_amount():
    policy = Policy()
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(amount=999999.0))
    assert result.decision == Decision.ALLOW


# --- Daily Limits ---


def test_daily_limit_accumulation():
    policy = Policy(limits=PolicyLimits(per_transaction=100.0, daily=150.0))
    gate = Gate(policy=policy)

    r1 = gate.evaluate(make_tx(amount=80.0))
    assert r1.decision == Decision.ALLOW

    r2 = gate.evaluate(make_tx(amount=80.0))
    assert r2.decision == Decision.DENY
    assert any(c.name == "daily_limit" for c in r2.failed_checks)


# --- Category Rules ---


def test_allowed_category():
    policy = Policy(
        merchants=MerchantRules(allowed_categories=["office_supplies", "saas"])
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(category="office_supplies"))
    assert result.decision == Decision.ALLOW


def test_blocked_category():
    policy = Policy(
        merchants=MerchantRules(allowed_categories=["office_supplies"])
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(category="gambling"))
    assert result.decision == Decision.DENY


def test_explicitly_blocked_category():
    policy = Policy(
        merchants=MerchantRules(blocked_categories=["gambling"])
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(category="gambling"))
    assert result.decision == Decision.DENY


# --- Merchant Rules ---


def test_blocked_merchant_exact():
    policy = Policy(
        merchants=MerchantRules(blocked_merchants=["casino-online.com"])
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(merchant="casino-online.com"))
    assert result.decision == Decision.DENY


def test_blocked_merchant_glob():
    policy = Policy(
        merchants=MerchantRules(blocked_merchants=["gambling.*"])
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(merchant="gambling.co.uk"))
    assert result.decision == Decision.DENY


def test_allowed_merchant_passes():
    policy = Policy(
        merchants=MerchantRules(blocked_merchants=["casino-online.com"])
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(merchant="staples.com"))
    assert result.decision == Decision.ALLOW


# --- Velocity ---


def test_cooldown_enforced():
    policy = Policy(velocity=VelocityRules(cooldown_seconds=60))
    gate = Gate(policy=policy)

    r1 = gate.evaluate(make_tx())
    assert r1.decision == Decision.ALLOW

    # Immediate second attempt
    r2 = gate.evaluate(make_tx())
    assert r2.decision == Decision.DENY
    assert any(c.name == "velocity" for c in r2.failed_checks)


def test_hourly_rate_limit():
    policy = Policy(velocity=VelocityRules(max_per_hour=3))
    gate = Gate(policy=policy)

    for i in range(3):
        r = gate.evaluate(make_tx(amount=1.0))
        assert r.decision == Decision.ALLOW

    r4 = gate.evaluate(make_tx(amount=1.0))
    assert r4.decision == Decision.DENY


# --- Escalation ---


def test_escalate_above_amount():
    policy = Policy(
        limits=PolicyLimits(per_transaction=500.0),
        escalation=EscalationRules(above_amount=100.0),
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(amount=150.0))
    assert result.decision == Decision.ESCALATE
    assert len(result.escalation_reasons) > 0


def test_escalate_new_merchant():
    policy = Policy(
        escalation=EscalationRules(on_new_merchant=True)
    )
    gate = Gate(policy=policy)

    # First tx — no escalation (no history yet)
    r1 = gate.evaluate(make_tx(merchant="known-store.com"))
    assert r1.decision == Decision.ALLOW

    # Same merchant — no escalation
    r2 = gate.evaluate(make_tx(merchant="known-store.com"))
    assert r2.decision == Decision.ALLOW

    # New merchant — escalate
    r3 = gate.evaluate(make_tx(merchant="new-store.com"))
    assert r3.decision == Decision.ESCALATE


def test_deny_overrides_escalation():
    """If a hard check fails, decision is DENY even if escalation would trigger."""
    policy = Policy(
        limits=PolicyLimits(per_transaction=50.0),
        escalation=EscalationRules(above_amount=30.0),
    )
    gate = Gate(policy=policy)
    result = gate.evaluate(make_tx(amount=75.0))
    assert result.decision == Decision.DENY


# --- Audit ---


def test_audit_log_recorded():
    policy = Policy(limits=PolicyLimits(per_transaction=50.0))
    gate = Gate(policy=policy)
    gate.evaluate(make_tx(amount=25.0))
    gate.evaluate(make_tx(amount=75.0))

    log = gate.audit_log
    assert len(log) == 2
    assert log[0].decision == Decision.ALLOW
    assert log[1].decision == Decision.DENY


# --- Decorator ---


def test_gated_decorator_allows():
    policy = Policy(limits=PolicyLimits(per_transaction=100.0))

    @gated(policy=policy)
    def buy(merchant, amount, category="general"):
        return f"bought from {merchant}"

    result = buy(merchant="store.com", amount=50.0)
    assert result == "bought from store.com"


def test_gated_decorator_denies():
    policy = Policy(limits=PolicyLimits(per_transaction=10.0))

    @gated(policy=policy)
    def buy(merchant, amount, category="general"):
        return "should not reach here"

    with pytest.raises(GatedTransactionDenied):
        buy(merchant="store.com", amount=50.0)


def test_gated_decorator_escalates():
    policy = Policy(
        limits=PolicyLimits(per_transaction=500.0),
        escalation=EscalationRules(above_amount=20.0),
    )

    @gated(policy=policy)
    def buy(merchant, amount, category="general"):
        return "should not reach here"

    with pytest.raises(GatedTransactionEscalated):
        buy(merchant="store.com", amount=50.0)


# --- Convenience Constructor ---


def test_simple_policy():
    policy = Policy.simple(
        max_per_transaction=100.0,
        max_daily=500.0,
        allowed_categories=["saas"],
        blocked_merchants=["bad.com"],
        require_escalation_above=75.0,
    )
    gate = Gate(policy=policy)

    # Allowed
    r1 = gate.evaluate(make_tx(amount=50.0, category="saas"))
    assert r1.decision == Decision.ALLOW

    # Wrong category
    r2 = gate.evaluate(make_tx(amount=50.0, category="gambling"))
    assert r2.decision == Decision.DENY

    # Blocked merchant
    r3 = gate.evaluate(make_tx(amount=50.0, category="saas", merchant="bad.com"))
    assert r3.decision == Decision.DENY

    # Escalation threshold
    r4 = gate.evaluate(make_tx(amount=90.0, category="saas"))
    assert r4.decision == Decision.ESCALATE


# --- Edge Cases ---


def test_negative_amount_raises():
    with pytest.raises(ValueError):
        Transaction(amount=-10, currency="USD", merchant="x", category="y", agent_id="z")


def test_empty_merchant_raises():
    with pytest.raises(ValueError):
        Transaction(amount=10, currency="USD", merchant="", category="y", agent_id="z")


def test_reset_clears_state():
    policy = Policy(limits=PolicyLimits(daily=100.0))
    gate = Gate(policy=policy)
    gate.evaluate(make_tx(amount=60.0))
    gate.reset()
    # After reset, daily total should be 0
    r = gate.evaluate(make_tx(amount=60.0))
    assert r.decision == Decision.ALLOW
