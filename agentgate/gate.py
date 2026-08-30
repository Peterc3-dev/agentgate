"""The Gate — core evaluation engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol

from .checks import ALL_CHECKS
from .ledger import InMemoryLedger
from .models import (
    AuditEntry,
    Check,
    CheckResult,
    Decision,
    EvaluationResult,
    Policy,
    Transaction,
)


class EscalationHandler(Protocol):
    """Protocol for handling escalated transactions."""

    async def escalate(
        self, transaction: Transaction, reasons: list[str]
    ) -> bool:
        """Return True to approve, False to deny."""
        ...


class LoggingEscalationHandler:
    """Default escalation handler — logs and denies."""

    async def escalate(
        self, transaction: Transaction, reasons: list[str]
    ) -> bool:
        print(f"[ESCALATION] tx={transaction.id} reasons={reasons}")
        return False  # deny by default — safe fallback


class Gate:
    """Main policy evaluation engine.

    Usage:
        gate = Gate(policy=my_policy)
        result = gate.evaluate(transaction)
        if result.passed:
            # proceed with payment
        elif result.decision == Decision.ESCALATE:
            # human review needed
        else:
            # denied — result.failed_checks has details
    """

    def __init__(
        self,
        policy: Policy,
        ledger: InMemoryLedger | None = None,
        escalation_handler: EscalationHandler | None = None,
        checks: list[Callable] | None = None,
        audit_log: list[AuditEntry] | None = None,
    ):
        self.policy = policy
        self.ledger = ledger or InMemoryLedger()
        self.escalation_handler = escalation_handler
        self._checks = checks or ALL_CHECKS
        self._audit_log: list[AuditEntry] = audit_log if audit_log is not None else []

    def evaluate(self, tx: Transaction) -> EvaluationResult:
        """Evaluate a transaction against the policy. Synchronous."""
        results: list[Check] = []
        escalation_reasons: list[str] = []

        for check_fn in self._checks:
            check = check_fn(tx=tx, policy=self.policy, ledger=self.ledger)
            results.append(check)

        # Separate hard failures from escalation
        hard_fails = [
            c for c in results
            if c.result == CheckResult.FAIL and c.name != "escalation"
        ]
        escalation_check = next(
            (c for c in results if c.name == "escalation"), None
        )

        # Determine decision
        if hard_fails:
            decision = Decision.DENY
        elif escalation_check and escalation_check.result == CheckResult.FAIL:
            decision = Decision.ESCALATE
            escalation_reasons = escalation_check.details.get("reasons", [])
        else:
            decision = Decision.ALLOW

        # Build audit entry
        audit = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            transaction_id=tx.id,
            agent_id=tx.agent_id,
            decision=decision,
            checks_passed=[c.name for c in results if c.result == CheckResult.PASS],
            checks_failed=[c.name for c in results if c.result == CheckResult.FAIL],
            escalation_reasons=escalation_reasons,
            reasoning=tx.reasoning,
            policy_name=self.policy.name,
            policy_version=self.policy.version,
        )
        self._audit_log.append(audit)

        # Record in ledger if allowed
        if decision == Decision.ALLOW:
            self.ledger.record(tx.agent_id, tx)

        result = EvaluationResult(
            decision=decision,
            transaction=tx,
            checks=results,
            escalation_reasons=escalation_reasons,
            audit=audit,
        )
        return result

    @property
    def audit_log(self) -> list[AuditEntry]:
        return list(self._audit_log)

    def reset(self) -> None:
        """Clear ledger and audit log. Useful for testing."""
        self.ledger.clear()
        self._audit_log.clear()
