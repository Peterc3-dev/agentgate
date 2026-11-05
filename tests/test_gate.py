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


def test_new_merchant_check_ignores_case():
    policy = Policy(escalation=EscalationRules(on_new_merchant=True))
    gate = Gate(policy=policy)

    r1 = gate.evaluate(make_tx(merchant="Amazon"))
    assert r1.decision == Decision.ALLOW

    r2 = gate.evaluate(make_tx(merchant="amazon"))
    assert r2.decision == Decision.ALLOW
    assert not r2.escalation_reasons


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


# --- Non-finite amounts ---


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_amount_raises(bad):
    with pytest.raises(ValueError):
        Transaction(amount=bad, currency="USD", merchant="x", category="y", agent_id="z")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "nan", "inf"])
def test_gated_decorator_rejects_non_finite_amount(bad):
    policy = Policy(limits=PolicyLimits(per_transaction=10.0, daily=20.0))
    gate = Gate(policy=policy)

    @gated(gate=gate)
    def buy(merchant, amount, category="general"):
        return "should not reach here"

    with pytest.raises(ValueError):
        buy(merchant="store.com", amount=bad)
    # Nothing was evaluated or recorded
    assert gate.audit_log == []


# --- Concurrency ---


def test_concurrent_evaluations_respect_daily_limit():
    """N threads each submit an amount that alone fits max_daily but together
    exceed it. Without serialising check-and-record, every thread can read a
    stale daily total and all be ALLOWed."""
    import threading
    import time
    from datetime import datetime, timezone

    from agentgate.ledger import InMemoryLedger

    class SlowLedger(InMemoryLedger):
        # Widen the window between reading the daily total and recording.
        def total_since(self, agent_id, since):
            total = super().total_since(agent_id, since)
            time.sleep(0.02)
            return total

    max_daily = 100.0
    amount = 60.0  # fits alone; any two together exceed max_daily
    n_threads = 8

    policy = Policy.simple(max_per_transaction=max_daily, max_daily=max_daily)
    ledger = SlowLedger()
    gate = Gate(policy=policy, ledger=ledger)

    barrier = threading.Barrier(n_threads)
    results = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()
        r = gate.evaluate(make_tx(amount=amount))
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == n_threads
    allowed = [r for r in results if r.decision == Decision.ALLOW]
    assert len(allowed) == 1
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert ledger.total_since("test-agent", start_of_day) <= max_daily


# --- Recorded timestamps ---


def test_backdated_timestamp_does_not_evade_daily_limit():
    from datetime import datetime, timedelta, timezone

    gate = Gate(policy=Policy(limits=PolicyLimits(daily=100.0)))
    old = datetime.now(timezone.utc) - timedelta(days=40)
    assert gate.evaluate(make_tx(amount=80.0, timestamp=old)).decision == Decision.ALLOW
    assert gate.evaluate(make_tx(amount=80.0, timestamp=old)).decision == Decision.DENY


def test_backdated_timestamp_does_not_evade_velocity():
    from datetime import datetime, timedelta, timezone

    gate = Gate(policy=Policy(velocity=VelocityRules(max_per_hour=1)))
    old = datetime.now(timezone.utc) - timedelta(days=2)
    assert gate.evaluate(make_tx(timestamp=old)).decision == Decision.ALLOW
    assert gate.evaluate(make_tx(timestamp=old)).decision == Decision.DENY


def test_naive_timestamp_rejected():
    from datetime import datetime

    with pytest.raises(ValueError):
        make_tx(timestamp=datetime.now())


# --- Currency ---


def test_currency_mismatch_denied():
    gate = Gate(policy=Policy(limits=PolicyLimits(per_transaction=50.0, currency="USD")))
    result = gate.evaluate(make_tx(amount=40.0, currency="JPY"))
    assert result.decision == Decision.DENY
    assert "currency" in [c.name for c in result.failed_checks]


def test_currency_match_case_insensitive():
    gate = Gate(policy=Policy(limits=PolicyLimits(currency="usd")))
    assert gate.evaluate(make_tx(currency="USD")).decision == Decision.ALLOW


# --- Overnight hours ---


def _freeze_check_clock(monkeypatch, hour):
    from datetime import datetime, timezone
    import agentgate.checks as checks_mod

    fixed = datetime(2026, 1, 5, hour, 30, tzinfo=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(checks_mod, "datetime", FrozenDatetime)


@pytest.mark.parametrize("hour,expected", [
    (23, Decision.ALLOW),
    (2, Decision.ALLOW),
    (6, Decision.DENY),
    (12, Decision.DENY),
])
def test_allowed_hours_wrap_past_midnight(monkeypatch, hour, expected):
    _freeze_check_clock(monkeypatch, hour)
    policy = Policy(time_restrictions=TimeRestrictions(allowed_hours=(22, 6)))
    assert Gate(policy=policy).evaluate(make_tx()).decision == expected


# --- Decorator records only completed payments ---


def test_gated_does_not_record_when_payment_fails():
    gate = Gate(policy=Policy(limits=PolicyLimits(daily=100.0)))

    @gated(gate=gate)
    def pay(merchant, amount, category="office_supplies"):
        raise RuntimeError("card declined")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            pay("staples.com", 60.0)
    assert gate.ledger.total_since("default-agent", _epoch()) == 0

    @gated(gate=gate)
    def pay_ok(merchant, amount, category="office_supplies"):
        return "ok"

    assert pay_ok("staples.com", 60.0) == "ok"
    assert gate.ledger.total_since("default-agent", _epoch()) == 60.0


def test_gated_async_does_not_record_when_payment_fails():
    import asyncio

    gate = Gate(policy=Policy(limits=PolicyLimits(daily=100.0)))

    @gated(gate=gate)
    async def pay(merchant, amount, category="office_supplies"):
        raise RuntimeError("card declined")

    with pytest.raises(RuntimeError):
        asyncio.run(pay("staples.com", 60.0))
    assert gate.ledger.total_since("default-agent", _epoch()) == 0


def _epoch():
    from datetime import datetime, timezone

    return datetime(1970, 1, 1, tzinfo=timezone.utc)


# --- Policy loading: path vs YAML string ---


def test_load_policy_single_line_yaml_ending_in_yaml_suffix():
    from agentgate.loader import load_policy

    assert load_policy("name: ops.yaml").name == "ops.yaml"


def test_load_policy_uppercase_suffix_and_extensionless_path(tmp_path):
    from agentgate.loader import load_policy

    for fname in ("POLICY.YAML", "policy"):
        f = tmp_path / fname
        f.write_text("name: from-file\nlimits:\n  daily: 200\n")
        assert load_policy(str(f)).limits.daily == 200


def test_load_policy_non_mapping_raises_value_error():
    from agentgate.loader import load_policy

    with pytest.raises(ValueError):
        load_policy("just a string")


# --- Decorator reserves spend while the payment is in flight ---


def test_concurrent_gated_calls_respect_daily_limit():
    """N threads call a @gated payment whose amount alone fits max_daily but
    any two together exceed it. check() runs under the lock but the payment
    runs outside it, so without a reservation every thread could pass."""
    import threading
    import time

    max_daily = 100.0
    amount = 60.0
    n_threads = 8

    gate = Gate(policy=Policy.simple(max_per_transaction=max_daily, max_daily=max_daily))
    barrier = threading.Barrier(n_threads)
    paid = []
    denied = []
    lock = threading.Lock()

    @gated(gate=gate)
    def pay(merchant, amount, category="office_supplies"):
        time.sleep(0.05)  # payment in flight, outside the gate's lock
        with lock:
            paid.append(amount)
        return "ok"

    def worker():
        barrier.wait()
        try:
            pay("staples.com", amount)
        except GatedTransactionDenied:
            with lock:
                denied.append(amount)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(paid) == 1
    assert len(denied) == n_threads - 1
    assert gate.ledger.total_since("default-agent", _epoch()) == amount


def test_gated_payment_exception_releases_reservation():
    import threading

    gate = Gate(policy=Policy(limits=PolicyLimits(daily=100.0)))
    in_flight = threading.Event()
    proceed = threading.Event()

    @gated(gate=gate)
    def pay(merchant, amount, category="office_supplies"):
        in_flight.set()
        proceed.wait(5)
        raise RuntimeError("card declined")

    errors = []

    def worker():
        try:
            pay("staples.com", 60.0)
        except RuntimeError as e:
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    assert in_flight.wait(5)
    # While the payment is in flight the reservation counts toward the limit.
    assert gate.ledger.total_since("default-agent", _epoch()) == 60.0
    with pytest.raises(GatedTransactionDenied):
        pay("staples.com", 60.0)
    proceed.set()
    t.join()

    assert len(errors) == 1
    assert gate.ledger.total_since("default-agent", _epoch()) == 0
    assert "staples.com" not in gate.ledger.get_known_merchants("default-agent")


def test_gate_check_reserves_and_release_or_commit_settles():
    gate = Gate(policy=Policy(limits=PolicyLimits(daily=100.0)))
    tx1 = make_tx(amount=60.0)
    tx2 = make_tx(amount=60.0)

    assert gate.check(tx1).decision == Decision.ALLOW
    # tx1 is reserved, so tx2 would exceed the daily limit.
    assert gate.check(tx2).decision == Decision.DENY
    gate.release(tx1)
    assert gate.ledger.total_since("test-agent", _epoch()) == 0

    assert gate.check(tx2).decision == Decision.ALLOW
    gate.commit(tx2)
    assert gate.ledger.total_since("test-agent", _epoch()) == 60.0
    assert "staples.com" in gate.ledger.get_known_merchants("test-agent")
    # Releasing a committed transaction is a no-op.
    gate.release(tx2)
    assert gate.ledger.total_since("test-agent", _epoch()) == 60.0
    assert gate.check(make_tx(amount=60.0)).decision == Decision.DENY


# --- Decorator currency ---


def test_gated_decorator_uses_policy_currency_by_default():
    policy = Policy(limits=PolicyLimits(per_transaction=100.0, currency="GBP"))

    @gated(policy=policy)
    def buy(merchant, amount):
        return "ok"

    assert buy("staples.com", 25.0) == "ok"


def test_gated_decorator_currency_param_mismatch_denied():
    policy = Policy(limits=PolicyLimits(per_transaction=100.0, currency="GBP"))
    calls = []

    @gated(policy=policy, currency_param="currency")
    def buy(merchant, amount, currency):
        calls.append(currency)
        return "ok"

    assert buy("staples.com", 25.0, "GBP") == "ok"
    assert buy("staples.com", 25.0, currency="gbp") == "ok"
    with pytest.raises(GatedTransactionDenied):
        buy("staples.com", 25.0, "USD")
    with pytest.raises(GatedTransactionDenied):
        buy("staples.com", 25.0, currency="EUR")
    assert calls == ["GBP", "gbp"]


def test_gated_async_decorator_currency_param_mismatch_denied():
    import asyncio

    policy = Policy(limits=PolicyLimits(per_transaction=100.0, currency="GBP"))

    @gated(policy=policy, currency_param="currency")
    async def buy(merchant, amount, currency="GBP"):
        return "ok"

    assert asyncio.run(buy("staples.com", 25.0)) == "ok"
    with pytest.raises(GatedTransactionDenied):
        asyncio.run(buy("staples.com", 25.0, "USD"))


# --- Escalation handler ---


class _FakeHandler:
    def __init__(self, approve):
        self.approve = approve
        self.calls = []

    async def escalate(self, transaction, reasons):
        self.calls.append((transaction.id, list(reasons)))
        return self.approve


def _escalating_gate(handler):
    policy = Policy(
        limits=PolicyLimits(daily=200.0),
        escalation=EscalationRules(above_amount=100.0),
    )
    return Gate(policy=policy, escalation_handler=handler)


def test_evaluate_async_approved_escalation_records_and_counts_toward_daily():
    import asyncio

    handler = _FakeHandler(approve=True)
    gate = _escalating_gate(handler)
    result = asyncio.run(gate.evaluate_async(make_tx(amount=150.0)))
    assert result.decision == Decision.ALLOW
    assert result.audit.escalation_outcome == "approved"
    assert len(handler.calls) == 1
    assert gate.ledger.total_since("test-agent", _epoch()) == 150.0
    # The approved spend counts toward the daily limit.
    over = asyncio.run(gate.evaluate_async(make_tx(amount=60.0)))
    assert over.decision == Decision.DENY
    assert "daily_limit" in [c.name for c in over.failed_checks]


def test_evaluate_async_rejected_escalation_records_nothing():
    import asyncio

    handler = _FakeHandler(approve=False)
    gate = _escalating_gate(handler)
    result = asyncio.run(gate.evaluate_async(make_tx(amount=150.0)))
    assert result.decision == Decision.DENY
    assert result.audit.decision == Decision.DENY
    assert result.audit.escalation_outcome == "rejected"
    assert result.audit.escalation_reasons
    assert gate.ledger.total_since("test-agent", _epoch()) == 0
    assert [a.decision for a in gate.audit_log] == [Decision.ESCALATE, Decision.DENY]


def test_evaluate_sync_does_not_call_handler():
    handler = _FakeHandler(approve=True)
    gate = _escalating_gate(handler)
    result = gate.evaluate(make_tx(amount=150.0))
    assert result.decision == Decision.ESCALATE
    assert handler.calls == []
    assert gate.ledger.total_since("test-agent", _epoch()) == 0


def test_gated_async_uses_handler_approve_and_reject():
    import asyncio

    approve_gate = _escalating_gate(_FakeHandler(approve=True))

    @gated(gate=approve_gate, agent_id="test-agent")
    async def pay(merchant, amount, category="office_supplies"):
        return "paid"

    assert asyncio.run(pay("staples.com", 150.0)) == "paid"
    assert approve_gate.ledger.total_since("test-agent", _epoch()) == 150.0

    reject_gate = _escalating_gate(_FakeHandler(approve=False))

    @gated(gate=reject_gate, agent_id="test-agent")
    async def pay2(merchant, amount, category="office_supplies"):
        return "paid"

    with pytest.raises(GatedTransactionDenied):
        asyncio.run(pay2("staples.com", 150.0))
    assert reject_gate.ledger.total_since("test-agent", _epoch()) == 0


# --- Policy value validation ---


def test_load_policy_rejects_string_amount():
    from agentgate import load_policy

    with pytest.raises(ValueError, match="limits.daily must be a number"):
        load_policy({"limits": {"daily": "200"}})


def test_policy_rejects_negative_limit():
    from agentgate import load_policy

    with pytest.raises(ValueError, match="cannot be negative"):
        PolicyLimits(per_transaction=-1.0)
    with pytest.raises(ValueError, match="cannot be negative"):
        load_policy({"limits": {"monthly": -5}})


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_policy_rejects_non_finite_limit(bad):
    with pytest.raises(ValueError, match="finite"):
        PolicyLimits(daily=bad)


def test_allowed_hours_out_of_range_rejected():
    from agentgate import load_policy

    with pytest.raises(ValueError, match="0..24"):
        TimeRestrictions(allowed_hours=(25, 3))
    with pytest.raises(ValueError, match="0..24"):
        load_policy({"time_restrictions": {"allowed_hours": [25, 3]}})
    with pytest.raises(ValueError, match="two integers"):
        load_policy({"time_restrictions": {"allowed_hours": [9]}})


def test_load_policy_valid_allowed_hours_is_tuple():
    from agentgate import load_policy

    policy = load_policy({"time_restrictions": {"allowed_hours": [9, 17]}})
    assert policy.time_restrictions.allowed_hours == (9, 17)


# --- Category case-insensitivity ---


@pytest.mark.parametrize("policy_cat,tx_cat", [("Software", "software"), ("software", "Software")])
def test_allowed_category_case_insensitive(policy_cat, tx_cat):
    gate = Gate(policy=Policy(merchants=MerchantRules(allowed_categories=[policy_cat])))
    assert gate.evaluate(make_tx(category=tx_cat)).decision == Decision.ALLOW


@pytest.mark.parametrize("policy_cat,tx_cat", [("Software", "software"), ("software", "SOFTWARE")])
def test_blocked_category_case_insensitive(policy_cat, tx_cat):
    gate = Gate(policy=Policy(merchants=MerchantRules(blocked_categories=[policy_cat])))
    result = gate.evaluate(make_tx(category=tx_cat))
    assert result.decision == Decision.DENY
    assert "category" in [c.name for c in result.failed_checks]


def test_loaded_policy_categories_case_insensitive():
    from agentgate import load_policy

    policy = load_policy({"merchants": {"allowed_categories": ["Software"], "blocked_categories": ["Gambling"]}})
    gate = Gate(policy=policy)
    assert gate.evaluate(make_tx(category="software")).decision == Decision.ALLOW
    assert gate.evaluate(make_tx(category="gambling")).decision == Decision.DENY


def test_load_policy_long_single_line_yaml_string():
    from agentgate.loader import load_policy

    long_name = "x" * 5000
    policy = load_policy(f"name: {long_name}")
    assert policy.name == long_name
