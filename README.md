# AgentGate

Open-source policy engine for agentic payments. Not a payment processor. Not a toll booth. The authorization layer between an AI agent and whatever payment API it's calling.

## Why

Every "agentic payments" startup is racing to insert themselves as middleware and clip 1-5 cents per transaction. AgentGate is the open alternative: a framework-agnostic policy engine that lets you define what an agent is allowed to spend, where, how much, and how often — without surrendering control to a rent-seeking intermediary.

## What It Does

- **Policy Schema** — Define spending rules in YAML or Python: per-transaction limits, daily/weekly/monthly caps, merchant category allowlists/blocklists, time-of-day restrictions
- **Evaluation Engine** — Takes a proposed transaction + policy → returns `ALLOW`, `DENY`, or `ESCALATE`
- **Human-in-the-Loop Hooks** — Pluggable escalation when transactions exceed policy bounds
- **Audit Trail** — Structured log of every decision with agent reasoning attached
- **Cooldown & Velocity Controls** — Prevent rapid-fire purchasing and runaway loops

## What It Doesn't Do

- Process payments (use Stripe, Square, PayPal, etc.)
- Store card numbers or tokens (use your payment provider's vault)
- Replace PCI compliance (that's between you and your provider)

## Install

```bash
pip install pyagentgate
```

## Quick Start

```python
from agentgate import Policy, Gate, Transaction

# Define a policy
policy = Policy.simple(
    max_per_transaction=50.00,
    max_daily=200.00,
    max_monthly=2000.00,
    allowed_categories=["groceries", "office_supplies", "saas"],
    blocked_merchants=["casino-online.com"],
    require_escalation_above=100.00,
)

# Create a gate
gate = Gate(policy=policy)

# Evaluate a transaction
tx = Transaction(
    amount=42.99,
    currency="USD",
    merchant="staples.com",
    category="office_supplies",
    agent_id="purchasing-agent-01",
    reasoning="Need printer paper for office",
)

result = gate.evaluate(tx)
# result.decision = Decision.ALLOW
# result.policy_checks = [...]
```

## Policy Schema (YAML)

```yaml
version: "1"
name: office-purchasing-agent
limits:
  per_transaction: 50.00
  daily: 200.00
  weekly: 750.00
  monthly: 2000.00
  currency: USD
merchants:
  allowed_categories:
    - office_supplies
    - saas
    - groceries
  blocked:
    - casino-online.com
    - gambling.*
velocity:
  max_transactions_per_hour: 10
  max_transactions_per_day: 50
  cooldown_seconds: 30
escalation:
  above_amount: 100.00
  on_new_merchant: true
  on_new_category: true
time_restrictions:
  allowed_hours: [9, 17]  # 9am-5pm only
  allowed_days: [0, 1, 2, 3, 4]  # Mon-Fri
```

## Custom Escalation Handlers

```python
from agentgate import Gate, EscalationHandler

class SlackEscalation(EscalationHandler):
    async def escalate(self, transaction, reasons):
        # Post to Slack, wait for approval
        approved = await self.post_to_slack(transaction, reasons)
        return approved

gate = Gate(policy=policy, escalation_handler=SlackEscalation())
```

**Current limitation:** `Gate.evaluate()` does not call `escalation_handler` today.
You can pass a handler to `Gate`, and it is stored on the gate, but nothing invokes it.
When a transaction needs escalation, `evaluate()` returns `Decision.ESCALATE` with
`escalation_reasons` filled in. Your code must check for that and call the handler itself.

## Concurrency

`Gate.evaluate()` holds a lock while it runs the checks and records an allowed
transaction. This stops two concurrent calls for the same agent from both passing a
cumulative limit, such as the daily cap.

The lock belongs to each `Gate` instance. It does not cover other `Gate` objects. If two
gates share one ledger, their evaluations are not serialised against each other. Use a
single `Gate` per ledger if you need limits enforced across threads.

## Amounts

Transaction amounts must be finite and not negative. `NaN` or infinity raises
`ValueError`, both from `Transaction(...)` and from the `@gated` decorator.

## Audit Log

Every evaluation produces an `AuditEntry`:

```python
result = gate.evaluate(tx)
print(result.audit)
# AuditEntry(
#   timestamp=2026-08-30T...,
#   transaction_id="tx_abc123",
#   agent_id="purchasing-agent-01",
#   decision=Decision.ALLOW,
#   checks_passed=["amount_limit", "category_allowed", "velocity_ok"],
#   checks_failed=[],
#   reasoning="Need printer paper for office",
#   policy_version="1",
# )
```

## Framework Integration

AgentGate is framework-agnostic. Use it with any agent framework:

```python
# LangChain tool wrapper
from agentgate.integrations import langchain_tool

# CrewAI tool wrapper  
from agentgate.integrations import crewai_tool

# Raw function — wrap any payment call
from agentgate import gated

@gated(policy=policy)
async def buy_item(merchant, amount, item):
    return await stripe.checkout(...)
```

## License

MIT — because the whole point is that nobody gets to gatekeep this.
