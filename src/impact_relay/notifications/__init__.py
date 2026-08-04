"""Notification channel adapters (contracts + fixture implementations)."""

from impact_relay.notifications.adapters import (
    APNsPushAdapter,
    APNsPushConfig,
    DeliveryResult,
    EmailAdapter,
    FCMConfig,
    FCMPushAdapter,
    FixtureEmailAdapter,
    FixturePushAdapter,
    NotificationConfigurationError,
    PostmarkConfig,
    PostmarkEmailAdapter,
    PushAdapter,
    SMTPConfig,
    SMTPEmailAdapter,
    open_email_adapter,
    open_push_adapter,
)

__all__ = [
    "APNsPushAdapter",
    "APNsPushConfig",
    "DeliveryResult",
    "EmailAdapter",
    "FCMConfig",
    "FCMPushAdapter",
    "FixtureEmailAdapter",
    "FixturePushAdapter",
    "NotificationConfigurationError",
    "PostmarkConfig",
    "PostmarkEmailAdapter",
    "PushAdapter",
    "SMTPConfig",
    "SMTPEmailAdapter",
    "open_email_adapter",
    "open_push_adapter",
]
