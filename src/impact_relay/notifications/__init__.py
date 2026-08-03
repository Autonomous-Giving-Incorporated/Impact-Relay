"""Notification channel adapters (contracts + fixture implementations)."""

from impact_relay.notifications.adapters import (
    APNsPushAdapter,
    DeliveryResult,
    EmailAdapter,
    FCMPushAdapter,
    FixtureEmailAdapter,
    FixturePushAdapter,
    NotificationConfigurationError,
    PushAdapter,
    SMTPConfig,
    SMTPEmailAdapter,
    open_email_adapter,
)

__all__ = [
    "APNsPushAdapter",
    "DeliveryResult",
    "EmailAdapter",
    "FCMPushAdapter",
    "FixtureEmailAdapter",
    "FixturePushAdapter",
    "NotificationConfigurationError",
    "PushAdapter",
    "SMTPConfig",
    "SMTPEmailAdapter",
    "open_email_adapter",
]
