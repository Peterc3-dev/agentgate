"""Basic AgentGate usage example."""

from agentgate import Decision, Gate, Policy, Transaction

# 1. Define a policy
policy = Policy.simple(
    max_per_transaction=50.00,
    max_daily=200.00,
    max_monthly=2000.00,
    allowed_categories=["groceries", "office_supplies", "saas"],
    blocked_merchants=["casino-online.com", "gambling.*"],
    require_escalation_above=100.00,
)

# 2. Create a gate
gate = Gate(policy=policy)

# 3. Evaluate transactions
transactions = [
    Transaction(
        amount=12.99,
        currency="USD",
        merchant="staples.com",
        category="office_supplies",
        agent_id="purchasing-bot",
        reasoning="Printer paper restock",
    ),
    Transaction(
        amount=75.00,
        currency="USD",
        merchant="casino-online.com",
        category="gambling",
        agent_id="purchasing-bot",
        reasoning="Team building activity",
    ),
    Transaction(
        amount=150.00,
        currency="USD",
        merchant="aws.amazon.com",
        category="saas",
        agent_id="purchasing-bot",
        reasoning="Monthly cloud hosting",
    ),
]

for tx in transactions:
    result = gate.evaluate(tx)
    print(f"\n{'='*60}")
    print(f"TX: {tx.merchant} — ${tx.amount} ({tx.category})")
    print(f"Decision: {result.decision.value.upper()}")
    if result.failed_checks:
        for check in result.failed_checks:
            print(f"  ✗ {check.name}: {check.message}")
    if result.escalation_reasons:
        for reason in result.escalation_reasons:
            print(f"  ⚠ {reason}")
    if result.passed:
        print(f"  ✓ All checks passed")

# 4. Review audit log
print(f"\n{'='*60}")
print(f"Audit log: {len(gate.audit_log)} entries")
for entry in gate.audit_log:
    print(f"  [{entry.decision.value}] {entry.transaction_id} — {entry.reasoning}")
