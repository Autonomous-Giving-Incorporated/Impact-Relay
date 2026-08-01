"""Notification channel adapters (contracts + fixture implementations)."""

from impact_relay.notifications.adapters import (
    APNsPushAdapter,
    DeliveryResult,
    EmailAdapter,
    FCMPushAdapter,
    FixtureEmailAdapter,
    FixturePushAdapter,
    PushAdapter,
)

__all__ = [
    "APNsPushAdapter",
    "DeliveryResult",
    "EmailAdapter",
    "FCMPushAdapter",
    "FixtureEmailAdapter",
    "FixturePushAdapter",
    "PushAdapter",
]
