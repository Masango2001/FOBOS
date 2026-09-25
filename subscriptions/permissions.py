"""Feature gates for the SaaS layer (§40, §53; spec §55–56).

- TRIAL (3 days): an explicit ~30 % feature subset (§56 requires an explicit
  list — never a computed "30 %" that breaks when new features are added).
- ACTIVE (paid): 100 % of features.
- Anything TRIAL beyond its 3 days → no access.

`feature_whitelist` is a pure function on the Subscription status string so the
serializers/views can render the granted feature list without DB calls.
"""

from __future__ import annotations

TRIAL_FEATURES = frozenset(
    {
        "dashboard",
        "products_crud",
        "stock_management",
        "pos",
        "sales_history",
        "basic_reports",
    }
)

FULL_FEATURES = frozenset(
    {
        "dashboard",
        "products_crud",
        "stock_management",
        "pos",
        "sales_history",
        "basic_reports",
        "advanced_reports",
        "advanced_analytics",
        "exports",
        "multi_branch",
        "automation_rules",
        "api",
        "priority_support",
    }
)


def feature_whitelist(status: str) -> list[str]:
    """Return the sorted features granted by a Subscription status.

    Canonical statuses (doc §39): "trial" | "active" | "expired" | "cancelled".
    ACTIVE → everything; TRIAL → trial subset; anything else → nothing.
    """
    if status == "active":
        return sorted(FULL_FEATURES)
    if status == "trial":
        return sorted(TRIAL_FEATURES)
    return []


def has_business_feature(business, feature: str) -> bool:
    """Return True when *business* has access to a single *feature*.

    Walks the current (non-cancelled, non-expired) subscription and applies the
    flow of §55: ACTIVE → whitelist(full); TRIAL → trial whitelist but only
    while the trial is still within its 3 days; anything expired → no access.
    """
    if business is None:
        return False
    subscription = business.subscriptions.filter(status__in=("active", "trial")).first()
    if subscription is None:
        return False
    if getattr(subscription, "is_expired", False):
        return False
    return feature in set(feature_whitelist(subscription.status))
