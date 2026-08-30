"""AgentGate — Open-source policy engine for agentic payments."""

from .decorators import GatedTransactionDenied, GatedTransactionEscalated, gated
from .gate import EscalationHandler, Gate, LoggingEscalationHandler
from .ledger import InMemoryLedger, LedgerBackend
from .loader import load_policy
from .models import (
    AuditEntry,
    Check,
    CheckResult,
    Decision,
    EscalationRules,
    EvaluationResult,
    MerchantRules,
    Policy,
    PolicyLimits,
    TimeRestrictions,
    Transaction,
    VelocityRules,
)

__version__ = "0.1.0"

__all__ = [
    # Core
    "Gate",
    "Policy",
    "Transaction",
    "Decision",
    "EvaluationResult",
    # Policy components
    "PolicyLimits",
    "MerchantRules",
    "VelocityRules",
    "EscalationRules",
    "TimeRestrictions",
    # Results
    "Check",
    "CheckResult",
    "AuditEntry",
    # Escalation
    "EscalationHandler",
    "LoggingEscalationHandler",
    # Ledger
    "InMemoryLedger",
    "LedgerBackend",
    # Loader
    "load_policy",
    # Decorator
    "gated",
    "GatedTransactionDenied",
    "GatedTransactionEscalated",
]
