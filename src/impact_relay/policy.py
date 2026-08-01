"""Versioned tenant policy loading (deterministic, no model evaluation).

Policies live under ``policies/tenants/`` as JSON or a restricted YAML subset
(maps, lists, scalars) so the runtime stays dependency-free.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_POLICY_DIR = Path(__file__).resolve().parents[2] / "policies" / "tenants"


class PolicyError(ValueError):
    """Invalid or missing policy pack."""


@dataclass(frozen=True)
class ConfidencePolicy:
    block_below: float = 0.75
    recommend_high: float = 0.95


@dataclass(frozen=True)
class EvidencePolicy:
    sufficient_kinds: tuple[str, ...] = ("invoice", "receipt", "accounting_ref")
    require_donor_visible: bool = True


@dataclass(frozen=True)
class AttributionPolicy:
    default_method: str = "DIRECT_RESTRICTED"
    allowed_methods: tuple[str, ...] = (
        "DIRECT_RESTRICTED",
        "PRO_RATA_POOL",
        "FIFO_ALLOCATION",
        "COHORT_ALLOCATION",
        "ASSET_SPONSORSHIP",
        "EXPENSE_BACKED",
        "MANUAL_APPROVED",
    )


@dataclass(frozen=True)
class NotificationPolicy:
    require_separate_send_approval: bool = True
    default_email_topics: tuple[str, ...] = ("MONEY_USED", "CORRECTION")
    fixture_consent_allowed: bool = True


@dataclass(frozen=True)
class AuthorityPolicy:
    l3_command_types: tuple[str, ...] = (
        "approve_expense",
        "reject_expense",
        "publish_use_of_funds_receipt",
        "send_notification",
        "publish_public_evidence",
        "change_attribution_policy",
        "correct_published_amount",
        "reverse_expense",
        "supersede_expense",
    )


@dataclass(frozen=True)
class TenantPolicy:
    """Deterministic policy pack for one tenant + version."""

    version: str
    tenant_id: str
    display_name: str = ""
    confidence: ConfidencePolicy = field(default_factory=ConfidencePolicy)
    evidence: EvidencePolicy = field(default_factory=EvidencePolicy)
    attribution: AttributionPolicy = field(default_factory=AttributionPolicy)
    notifications: NotificationPolicy = field(default_factory=NotificationPolicy)
    authority: AuthorityPolicy = field(default_factory=AuthorityPolicy)
    source_path: str | None = None

    def requires_human(self, command_type: str) -> bool:
        return command_type in self.authority.l3_command_types

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "confidence": {
                "block_below": self.confidence.block_below,
                "recommend_high": self.confidence.recommend_high,
            },
            "evidence": {
                "sufficient_kinds": list(self.evidence.sufficient_kinds),
                "require_donor_visible": self.evidence.require_donor_visible,
            },
            "attribution": {
                "default_method": self.attribution.default_method,
                "allowed_methods": list(self.attribution.allowed_methods),
            },
            "notifications": {
                "require_separate_send_approval": (
                    self.notifications.require_separate_send_approval
                ),
                "default_email_topics": list(self.notifications.default_email_topics),
                "fixture_consent_allowed": self.notifications.fixture_consent_allowed,
            },
            "authority": {
                "l3_command_types": list(self.authority.l3_command_types),
            },
            "source_path": self.source_path,
        }


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(p) for p in inner.split(",")]
    return s


def _load_restricted_yaml(text: str) -> dict[str, Any]:
    """Parse restricted YAML: nested maps, bullet lists, scalars, inline lists."""
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise PolicyError("policy root must be a mapping")
        return data

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- "):
            item_raw = content[2:].strip()
            if not isinstance(parent, list):
                raise PolicyError(f"list item without list parent: {content!r}")
            parent.append(_parse_scalar(item_raw))
            continue

        if ":" not in content:
            raise PolicyError(f"expected key: value, got {content!r}")

        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()
        if not isinstance(parent, dict):
            raise PolicyError(f"map key under non-map: {key}")

        if rest == "":
            j = i
            is_list = False
            while j < len(lines):
                peek = lines[j]
                j += 1
                if not peek.strip() or peek.lstrip().startswith("#"):
                    continue
                child_indent = len(peek) - len(peek.lstrip(" "))
                if child_indent <= indent:
                    break
                is_list = peek.strip().startswith("- ")
                break
            child: Any = [] if is_list else {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(rest)

    return root


def load_policy_document(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise PolicyError(f"policy file not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = _load_restricted_yaml(text)
    if not isinstance(data, dict):
        raise PolicyError("policy root must be a mapping")
    return data


def parse_tenant_policy(
    data: dict[str, Any], *, source_path: str | None = None
) -> TenantPolicy:
    version = str(data.get("version") or data.get("policy_version") or "")
    tenant_id = str(data.get("tenant_id") or data.get("organization_id") or "")
    if not version:
        raise PolicyError("policy.version is required")
    if not tenant_id:
        raise PolicyError("policy.tenant_id is required")

    conf = data.get("confidence") or {}
    evid = data.get("evidence") or {}
    attr = data.get("attribution") or {}
    notif = data.get("notifications") or {}
    auth = data.get("authority") or {}

    defaults_auth = AuthorityPolicy()
    defaults_attr = AttributionPolicy()

    return TenantPolicy(
        version=version,
        tenant_id=tenant_id,
        display_name=str(data.get("display_name") or data.get("name") or ""),
        confidence=ConfidencePolicy(
            block_below=float(conf.get("block_below", 0.75)),
            recommend_high=float(conf.get("recommend_high", 0.95)),
        ),
        evidence=EvidencePolicy(
            sufficient_kinds=tuple(
                evid.get("sufficient_kinds")
                or evid.get("min_kinds")
                or ("invoice", "receipt", "accounting_ref")
            ),
            require_donor_visible=bool(evid.get("require_donor_visible", True)),
        ),
        attribution=AttributionPolicy(
            default_method=str(attr.get("default_method", "DIRECT_RESTRICTED")),
            allowed_methods=tuple(
                attr.get("allowed_methods") or defaults_attr.allowed_methods
            ),
        ),
        notifications=NotificationPolicy(
            require_separate_send_approval=bool(
                notif.get("require_separate_send_approval", True)
            ),
            default_email_topics=tuple(
                notif.get("default_email_topics") or ("MONEY_USED", "CORRECTION")
            ),
            fixture_consent_allowed=bool(notif.get("fixture_consent_allowed", True)),
        ),
        authority=AuthorityPolicy(
            l3_command_types=tuple(
                auth.get("l3_command_types") or defaults_auth.l3_command_types
            ),
        ),
        source_path=source_path,
    )


def tenant_slug(tenant_id: str) -> str:
    slug = tenant_id
    if slug.startswith("org_"):
        slug = slug[4:]
    return slug.replace("_", "-")


def resolve_policy_path(
    tenant_id: str,
    version: str = "v1.0",
    *,
    policy_dir: Path | str | None = None,
) -> Path:
    base = Path(policy_dir) if policy_dir else DEFAULT_POLICY_DIR
    slug = tenant_slug(tenant_id)
    candidates = [
        base / f"{slug}.{version}.yaml",
        base / f"{slug}.{version}.yml",
        base / f"{slug}.{version}.json",
        base / f"{slug}.yaml",
        base / f"{slug}.yml",
        base / f"{slug}.json",
        base / f"{tenant_id}.{version}.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise PolicyError(
        f"no policy file for tenant_id={tenant_id!r} version={version!r} in {base}"
    )


def _tenant_ids_compatible(policy_tenant: str, requested: str) -> bool:
    if policy_tenant == requested:
        return True
    a = policy_tenant.replace("-", "_")
    b = requested.replace("-", "_")
    if a == b:
        return True
    if b == f"org_{a}" or a == f"org_{b}":
        return True
    if b.endswith(a) or a.endswith(b.replace("org_", "")):
        return True
    return False


def load_tenant_policy(
    tenant_id: str,
    version: str = "v1.0",
    *,
    policy_dir: Path | str | None = None,
) -> TenantPolicy:
    path = resolve_policy_path(tenant_id, version, policy_dir=policy_dir)
    data = load_policy_document(path)
    policy = parse_tenant_policy(data, source_path=str(path))
    if not _tenant_ids_compatible(policy.tenant_id, tenant_id):
        raise PolicyError(
            f"policy tenant_id {policy.tenant_id!r} does not match {tenant_id!r}"
        )
    return policy


def default_policy(
    tenant_id: str = "org_hacker_dojo", version: str = "v1.0"
) -> TenantPolicy:
    """Load file-backed policy, or built-in defaults if missing."""
    try:
        return load_tenant_policy(tenant_id, version)
    except PolicyError:
        return TenantPolicy(
            version=version, tenant_id=tenant_id, display_name=tenant_id
        )
