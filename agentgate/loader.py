"""Load policies from YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import (
    EscalationRules,
    MerchantRules,
    Policy,
    PolicyLimits,
    TimeRestrictions,
    VelocityRules,
)

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def load_policy(source: str | Path | dict) -> Policy:
    """Load a policy from a YAML file path, YAML string, or dict.

    Args:
        source: File path, YAML string, or already-parsed dict.

    Returns:
        A Policy instance.
    """
    if isinstance(source, dict):
        data = source
    elif isinstance(source, Path) or (
        isinstance(source, str) and _looks_like_path(source)
    ):
        if not HAS_YAML:
            raise ImportError("PyYAML required: pip install pyyaml")
        with open(source) as f:
            data = yaml.safe_load(f)
    else:
        if not HAS_YAML:
            raise ImportError("PyYAML required: pip install pyyaml")
        data = yaml.safe_load(source)

    if not isinstance(data, dict):
        raise ValueError(
            f"Policy source must contain a mapping, got {type(data).__name__}"
        )
    return _dict_to_policy(data)


def _looks_like_path(source: str) -> bool:
    """Decide whether a string names a file rather than containing YAML."""
    if "\n" in source or source.strip().startswith("{"):
        return False
    if Path(source).is_file():
        return True
    # A single-line YAML document such as "name: ops.yaml" also ends in .yaml;
    # only treat it as a path when it has no "key: value" separator.
    return Path(source).suffix.lower() in (".yaml", ".yml") and ": " not in source


def _dict_to_policy(data: dict[str, Any]) -> Policy:
    """Convert a raw dict to a Policy."""
    limits_data = data.get("limits", {})
    limits = PolicyLimits(
        per_transaction=limits_data.get("per_transaction"),
        daily=limits_data.get("daily"),
        weekly=limits_data.get("weekly"),
        monthly=limits_data.get("monthly"),
        currency=limits_data.get("currency", "USD"),
    )

    merch_data = data.get("merchants", {})
    merchants = MerchantRules(
        allowed_categories=merch_data.get("allowed_categories"),
        blocked_categories=merch_data.get("blocked_categories", []),
        allowed_merchants=merch_data.get("allowed_merchants"),
        blocked_merchants=merch_data.get("blocked_merchants", []),
    )

    vel_data = data.get("velocity", {})
    velocity = VelocityRules(
        max_per_hour=vel_data.get("max_transactions_per_hour"),
        max_per_day=vel_data.get("max_transactions_per_day"),
        cooldown_seconds=vel_data.get("cooldown_seconds", 0),
    )

    esc_data = data.get("escalation", {})
    escalation = EscalationRules(
        above_amount=esc_data.get("above_amount"),
        on_new_merchant=esc_data.get("on_new_merchant", False),
        on_new_category=esc_data.get("on_new_category", False),
        on_cumulative_above=esc_data.get("on_cumulative_above"),
    )

    time_data = data.get("time_restrictions", {})
    time_rules = TimeRestrictions(
        # TimeRestrictions validates the shape and range (two ints in 0..24).
        allowed_hours=time_data.get("allowed_hours"),
        allowed_days=time_data.get("allowed_days"),
    )

    return Policy(
        name=data.get("name", "default"),
        version=str(data.get("version", "1")),
        limits=limits,
        merchants=merchants,
        velocity=velocity,
        escalation=escalation,
        time_restrictions=time_rules,
    )
