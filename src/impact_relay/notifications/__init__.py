"""Notification channel adapters (contracts + fixture implementations)."""

from impact_relay.notifications.adapters import (
    APNsPushAdapter,
    APNsPushConfig,
    DeliveryResult,
    EmailAdapter,
    FCMPushAdapter,
    FCMConfig,
    FixtureEmailAdapter,
    FixturePushAdapter,
    NotificationConfigurationError,
    PostmarkConfig,
    PostmarkEmailAdapter,
    PushAdapter,
    SMTPConfig,
    SMTPEmailAdapter,
    open_push_adapter,
    open_email_adapter,
)

__all__ = [
    "APNsPushAdapter",
    "DeliveryResult",
    "EmailAdapter",
    "FCMPushAdapter",
    "FCMConfig",
    "APNsPushConfig",
    "FixtureEmailAdapter",
    "FixturePushAdapter",
    "NotificationConfigurationError",
    "PostmarkConfig",
    "PostmarkEmailAdapter",
    "PushAdapter",
    "SMTPConfig",
    "SMTPEmailAdapter",
    "open_push_adapter",
    "open_email_adapter",
]
