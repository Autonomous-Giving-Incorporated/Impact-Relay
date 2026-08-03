"""Channel adapter contracts and governed transport implementations.

Fixture adapters keep Hacker Dojo pilot offline and deterministic. SMTP and
Postmark email transports are shipped; APNs/FCM remain host integration points.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from impact_relay.domain.types import NotificationIntent


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    provider_receipt: str
    detail: str = ""
    permanent_failure: bool = False

    def as_tuple(self) -> tuple[bool, str, str]:
        detail = self.detail
        if self.permanent_failure and "permanent" not in detail.lower():
            detail = f"permanent: {detail}" if detail else "permanent failure"
        return self.success, self.provider_receipt, detail


class NotificationConfigurationError(ValueError):
    """Invalid production notification configuration."""


def _is_single_email_address(value: str) -> bool:
    return bool(
        value
        and value.count("@") == 1
        and not any(ch.isspace() or ch in ",;<>\x00" for ch in value)
    )


@dataclass(frozen=True)
class SMTPConfig:
    """Validated SMTP transport configuration without secret-bearing repr output."""

    host: str
    port: int
    from_address: str
    username: str = ""
    password: str = field(default="", repr=False)
    tls_mode: str = "starttls"
    timeout_seconds: float = 10.0
    reply_to: str = ""

    def __post_init__(self) -> None:
        mode = self.tls_mode.strip().lower()
        object.__setattr__(self, "tls_mode", mode)
        if not self.host.strip():
            raise NotificationConfigurationError("SMTP host is required")
        if not 1 <= self.port <= 65535:
            raise NotificationConfigurationError("SMTP port must be between 1 and 65535")
        if not _is_single_email_address(self.from_address):
            raise NotificationConfigurationError("SMTP from address must be an email address")
        if bool(self.username) != bool(self.password):
            raise NotificationConfigurationError(
                "SMTP username and password must either both be set or both be omitted"
            )
        if mode not in {"starttls", "ssl", "none"}:
            raise NotificationConfigurationError("SMTP TLS mode must be starttls, ssl, or none")
        if self.timeout_seconds <= 0:
            raise NotificationConfigurationError("SMTP timeout must be positive")
        if self.reply_to and not _is_single_email_address(self.reply_to):
            raise NotificationConfigurationError("SMTP reply-to must be an email address")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SMTPConfig:
        values = env if env is not None else os.environ
        try:
            port = int(values.get("IMPACT_RELAY_SMTP_PORT", "587"))
            timeout = float(values.get("IMPACT_RELAY_SMTP_TIMEOUT_SECONDS", "10"))
        except ValueError as exc:
            raise NotificationConfigurationError("SMTP port and timeout must be numeric") from exc
        return cls(
            host=values.get("IMPACT_RELAY_SMTP_HOST", ""),
            port=port,
            from_address=values.get("IMPACT_RELAY_SMTP_FROM", ""),
            username=values.get("IMPACT_RELAY_SMTP_USERNAME", ""),
            password=values.get("IMPACT_RELAY_SMTP_PASSWORD", ""),
            tls_mode=values.get("IMPACT_RELAY_SMTP_TLS", "starttls"),
            timeout_seconds=timeout,
            reply_to=values.get("IMPACT_RELAY_SMTP_REPLY_TO", ""),
        )


@dataclass(frozen=True)
class PostmarkConfig:
    """Validated Postmark transport configuration with a redacted server token."""

    server_token: str = field(repr=False)
    from_address: str
    reply_to: str = ""
    message_stream: str = "outbound"
    timeout_seconds: float = 10.0
    endpoint: str = "https://api.postmarkapp.com/email"

    def __post_init__(self) -> None:
        if not self.server_token.strip():
            raise NotificationConfigurationError("Postmark server token is required")
        if not _is_single_email_address(self.from_address):
            raise NotificationConfigurationError("Postmark from address must be an email address")
        if self.reply_to and not _is_single_email_address(self.reply_to):
            raise NotificationConfigurationError("Postmark reply-to must be an email address")
        if not self.message_stream.strip():
            raise NotificationConfigurationError("Postmark message stream is required")
        if self.timeout_seconds <= 0:
            raise NotificationConfigurationError("Postmark timeout must be positive")
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise NotificationConfigurationError("Postmark endpoint must be an absolute HTTPS URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise NotificationConfigurationError(
                "Postmark endpoint must not contain userinfo, a query, or a fragment"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PostmarkConfig:
        values = env if env is not None else os.environ
        try:
            timeout = float(values.get("IMPACT_RELAY_POSTMARK_TIMEOUT_SECONDS", "10"))
        except ValueError as exc:
            raise NotificationConfigurationError("Postmark timeout must be numeric") from exc
        return cls(
            server_token=values.get("IMPACT_RELAY_POSTMARK_SERVER_TOKEN", ""),
            from_address=values.get("IMPACT_RELAY_POSTMARK_FROM", ""),
            reply_to=values.get("IMPACT_RELAY_POSTMARK_REPLY_TO", ""),
            message_stream=values.get("IMPACT_RELAY_POSTMARK_MESSAGE_STREAM", "outbound"),
            timeout_seconds=timeout,
            endpoint=values.get(
                "IMPACT_RELAY_POSTMARK_ENDPOINT", "https://api.postmarkapp.com/email"
            ),
        )


@runtime_checkable
class EmailAdapter(Protocol):
    provider_name: str

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> DeliveryResult: ...

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        """NotificationService-compatible entrypoint."""
        ...


@runtime_checkable
class PushAdapter(Protocol):
    provider_name: str

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult: ...

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]: ...


class FixtureEmailAdapter:
    """In-process email — no network (pilot / tests)."""

    provider_name = "fixture_email"
    fixture_consent_bootstrap = True

    def __init__(self, *, fail: bool = False, permanent: bool = False) -> None:
        self.fail = fail
        self.permanent = permanent
        self.sent: list[dict[str, Any]] = []

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> DeliveryResult:
        self.sent.append(
            {
                "to": to_address,
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
                "metadata": metadata or {},
            }
        )
        if self.fail:
            return DeliveryResult(
                False,
                f"fail_{len(self.sent)}",
                "bounce" if self.permanent else "temporary error",
                permanent_failure=self.permanent,
            )
        return DeliveryResult(True, f"msg_{len(self.sent)}", "accepted")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        to = str(intent.payload.get("donor_email") or f"{intent.donor_id}@example.invalid")
        subject = f"[{intent.message_class.value}] Impact Relay update"
        body = str(intent.payload.get("description") or intent.source_id)
        return self.send_email(to_address=to, subject=subject, body_text=body).as_tuple()


SMTPClientFactory = Callable[[SMTPConfig], Any]
EmailAddressResolver = Callable[[NotificationIntent], str]
PostmarkOpener = Callable[[Request, float], Any]


def _open_smtp_client(config: SMTPConfig) -> Any:
    if config.tls_mode == "ssl":
        return smtplib.SMTP_SSL(
            config.host,
            config.port,
            timeout=config.timeout_seconds,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(config.host, config.port, timeout=config.timeout_seconds)


class SMTPEmailAdapter:
    """Production-capable SMTP email transport using the standard library.

    Recipient lookup remains host-owned. The resolver receives the consent-checked
    ``NotificationIntent`` and must return one address for that donor.
    """

    provider_name = "smtp"

    def __init__(
        self,
        config: SMTPConfig,
        *,
        address_resolver: EmailAddressResolver | None = None,
        client_factory: SMTPClientFactory | None = None,
    ) -> None:
        self.config = config
        self.address_resolver = address_resolver
        self._client_factory = client_factory or _open_smtp_client

    def _recipient_for(self, intent: NotificationIntent) -> str:
        address = (
            self.address_resolver(intent)
            if self.address_resolver is not None
            else str(intent.payload.get("donor_email") or "")
        )
        if not _is_single_email_address(address):
            raise NotificationConfigurationError(
                "SMTP delivery requires a host-provided donor email resolver"
            )
        return address

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> DeliveryResult:
        message = EmailMessage()
        message["From"] = self.config.from_address
        message["To"] = to_address
        message["Subject"] = subject
        if self.config.reply_to:
            message["Reply-To"] = self.config.reply_to
        domain = self.config.from_address.rsplit("@", 1)[-1]
        message_id = make_msgid(domain=domain)
        message["Message-ID"] = message_id
        for key, value in sorted((metadata or {}).items()):
            safe_key = "".join(ch if ch.isalnum() else "-" for ch in key).strip("-")
            if safe_key and "\n" not in value and "\r" not in value:
                message[f"X-Impact-{safe_key}"] = value
        message.set_content(body_text)
        if body_html:
            message.add_alternative(body_html, subtype="html")

        try:
            with self._client_factory(self.config) as client:
                if self.config.tls_mode == "starttls":
                    client.starttls(context=ssl.create_default_context())
                if self.config.username:
                    client.login(self.config.username, self.config.password)
                refused = client.send_message(message)
                if refused:
                    return DeliveryResult(
                        False,
                        message_id,
                        "permanent: recipient rejected by SMTP server",
                        permanent_failure=True,
                    )
            return DeliveryResult(True, message_id, "accepted by SMTP server")
        except smtplib.SMTPRecipientsRefused:
            return DeliveryResult(
                False,
                message_id,
                "permanent: recipient rejected by SMTP server",
                permanent_failure=True,
            )
        except smtplib.SMTPSenderRefused:
            return DeliveryResult(
                False,
                message_id,
                "permanent: sender rejected by SMTP server",
                permanent_failure=True,
            )
        except smtplib.SMTPAuthenticationError:
            return DeliveryResult(
                False,
                message_id,
                "permanent: SMTP authentication failed",
                permanent_failure=True,
            )
        except smtplib.SMTPResponseException as exc:
            permanent = exc.smtp_code >= 500
            prefix = "permanent: " if permanent else ""
            return DeliveryResult(
                False,
                message_id,
                f"{prefix}SMTP server returned status {exc.smtp_code}",
                permanent_failure=permanent,
            )
        except (OSError, TimeoutError, smtplib.SMTPException):
            return DeliveryResult(False, message_id, "temporary SMTP transport failure")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        try:
            recipient = self._recipient_for(intent)
        except NotificationConfigurationError as exc:
            return DeliveryResult(
                False,
                "",
                f"permanent: {exc}",
                permanent_failure=True,
            ).as_tuple()
        except Exception:  # noqa: BLE001 - host resolver details may contain donor PII
            return DeliveryResult(
                False,
                "",
                "permanent: donor email resolution failed",
                permanent_failure=True,
            ).as_tuple()
        subject = str(
            intent.payload.get("email_subject")
            or f"[{intent.message_class.value}] Impact Relay update"
        )
        body_text = str(
            intent.payload.get("email_body_text")
            or intent.payload.get("description")
            or intent.source_id
        )
        body_html_raw = intent.payload.get("email_body_html")
        body_html = str(body_html_raw) if body_html_raw else None
        return self.send_email(
            to_address=recipient,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            metadata={
                "intent-id": intent.id,
                "tenant-id": intent.organization_id,
                "source-id": intent.source_id,
            },
        ).as_tuple()


def _open_postmark(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)


class PostmarkEmailAdapter:
    """Postmark transactional email transport using the governed email boundary."""

    provider_name = "postmark"

    def __init__(
        self,
        config: PostmarkConfig,
        *,
        address_resolver: EmailAddressResolver | None = None,
        opener: PostmarkOpener | None = None,
    ) -> None:
        self.config = config
        self.address_resolver = address_resolver
        self._opener = opener or _open_postmark

    def _recipient_for(self, intent: NotificationIntent) -> str:
        address = (
            self.address_resolver(intent)
            if self.address_resolver is not None
            else str(intent.payload.get("donor_email") or "")
        )
        if not _is_single_email_address(address):
            raise NotificationConfigurationError(
                "Postmark delivery requires a host-provided donor email resolver"
            )
        return address

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> DeliveryResult:
        payload: dict[str, Any] = {
            "From": self.config.from_address,
            "To": to_address,
            "Subject": subject,
            "TextBody": body_text,
            "MessageStream": self.config.message_stream,
            "Metadata": metadata or {},
        }
        if body_html:
            payload["HtmlBody"] = body_html
        if self.config.reply_to:
            payload["ReplyTo"] = self.config.reply_to
        request = Request(
            self.config.endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": self.config.server_token,
                "User-Agent": "impact-relay/0.9",
            },
            method="POST",
        )
        try:
            with self._opener(request, self.config.timeout_seconds) as response:
                content_type = str(response.headers.get("Content-Type", ""))
                media_type = content_type.partition(";")[0].strip().lower()
                if media_type != "application/json" and not media_type.endswith("+json"):
                    return DeliveryResult(False, "", "temporary invalid Postmark response")
                body = response.read(65_537)
        except HTTPError as exc:
            permanent = 400 <= exc.code < 500 and exc.code != 429
            prefix = "permanent: " if permanent else ""
            return DeliveryResult(
                False,
                "",
                f"{prefix}Postmark returned HTTP {exc.code}",
                permanent_failure=permanent,
            )
        except (URLError, OSError, TimeoutError):
            return DeliveryResult(False, "", "temporary Postmark transport failure")

        if len(body) > 65_536:
            return DeliveryResult(False, "", "temporary invalid Postmark response")
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return DeliveryResult(False, "", "temporary invalid Postmark response")
        if not isinstance(result, dict):
            return DeliveryResult(False, "", "temporary invalid Postmark response")
        message_id = str(result.get("MessageID") or "")
        error_code = result.get("ErrorCode")
        if error_code == 0 and message_id:
            return DeliveryResult(True, message_id, "accepted by Postmark")
        if isinstance(error_code, int) and error_code != 0:
            return DeliveryResult(
                False,
                message_id,
                f"permanent: Postmark rejected message with error code {error_code}",
                permanent_failure=True,
            )
        return DeliveryResult(False, message_id, "temporary invalid Postmark response")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        try:
            recipient = self._recipient_for(intent)
        except NotificationConfigurationError as exc:
            return DeliveryResult(False, "", f"permanent: {exc}", permanent_failure=True).as_tuple()
        except Exception:  # noqa: BLE001 - host resolver details may contain donor PII
            return DeliveryResult(
                False,
                "",
                "permanent: donor email resolution failed",
                permanent_failure=True,
            ).as_tuple()
        subject = str(
            intent.payload.get("email_subject")
            or f"[{intent.message_class.value}] Impact Relay update"
        )
        body_text = str(
            intent.payload.get("email_body_text")
            or intent.payload.get("description")
            or intent.source_id
        )
        body_html_raw = intent.payload.get("email_body_html")
        return self.send_email(
            to_address=recipient,
            subject=subject,
            body_text=body_text,
            body_html=str(body_html_raw) if body_html_raw else None,
            metadata={
                "intent-id": intent.id,
                "tenant-id": intent.organization_id,
                "source-id": intent.source_id,
            },
        ).as_tuple()


def open_email_adapter(
    *,
    backend: str | None = None,
    env: Mapping[str, str] | None = None,
    address_resolver: EmailAddressResolver | None = None,
    client_factory: SMTPClientFactory | None = None,
    postmark_opener: PostmarkOpener | None = None,
) -> EmailAdapter:
    """Open the explicit fixture, SMTP, or Postmark email backend.

    Production configuration is validated immediately. No fallback to fixture
    delivery occurs after ``smtp`` or ``postmark`` is selected.
    """

    values = env if env is not None else os.environ
    kind = (backend or values.get("IMPACT_RELAY_EMAIL_BACKEND") or "fixture").lower().strip()
    if kind == "fixture":
        return FixtureEmailAdapter()
    if kind == "smtp":
        return SMTPEmailAdapter(
            SMTPConfig.from_env(values),
            address_resolver=address_resolver,
            client_factory=client_factory,
        )
    if kind == "postmark":
        return PostmarkEmailAdapter(
            PostmarkConfig.from_env(values),
            address_resolver=address_resolver,
            opener=postmark_opener,
        )
    raise NotificationConfigurationError(
        f"unknown IMPACT_RELAY_EMAIL_BACKEND={kind!r} (use fixture, smtp, or postmark)"
    )


class FixturePushAdapter:
    """In-process push stand-in for APNs/FCM."""

    provider_name = "fixture_push"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        self.sent.append({"token": device_token, "title": title, "body": body, "data": data or {}})
        if self.fail:
            return DeliveryResult(False, "push_fail", "device unreachable")
        return DeliveryResult(True, f"push_{len(self.sent)}", "queued")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        token = str(intent.payload.get("device_token") or "fixture-token")
        return self.send_push(
            device_token=token,
            title=intent.message_class.value,
            body=str(intent.source_id),
            data={"intent_id": intent.id},
        ).as_tuple()


class APNsPushAdapter:
    """Contract placeholder — host supplies credentials and HTTP/2 client.

    Not for production use until configured; raises if deliver is called.
    """

    provider_name = "apns"

    def __init__(self, *, team_id: str = "", key_id: str = "", bundle_id: str = "") -> None:
        self.team_id = team_id
        self.key_id = key_id
        self.bundle_id = bundle_id

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        raise NotImplementedError("Configure host APNs client; use FixturePushAdapter for pilot")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        raise NotImplementedError("APNs not configured")


class FCMPushAdapter:
    """Contract placeholder for Firebase Cloud Messaging."""

    provider_name = "fcm"

    def __init__(self, *, project_id: str = "") -> None:
        self.project_id = project_id

    def send_push(
        self,
        *,
        device_token: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        raise NotImplementedError("Configure host FCM client; use FixturePushAdapter for pilot")

    def deliver(self, intent: NotificationIntent) -> tuple[bool, str, str]:
        raise NotImplementedError("FCM not configured")
