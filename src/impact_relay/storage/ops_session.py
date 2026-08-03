"""Safe, versioned JSON codec for local workflow operator sessions.

The codec deliberately supports only Impact Relay's in-memory session graph and a
small set of standard-library value types. It never imports or executes a class
named by session data, calls constructors, or invokes ``__setstate__``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import threading
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from impact_relay import agents, domain, workflows
from impact_relay.agents.ledger_binding import InMemoryLedgerBinding
from impact_relay.domain.ledger import Ledger
from impact_relay.domain.tenant import TenantWorkspace
from impact_relay.workflows.store_memory import InMemoryWorkflowStore

SESSION_FORMAT = "impact-relay-ops-session"
SESSION_VERSION = 1


class SessionFormatError(ValueError):
    """Session data is malformed, unsupported, or fails integrity validation."""


def _trusted_classes() -> dict[str, type[Any]]:
    """Build the fixed class registry from already-imported trusted modules."""
    registry: dict[str, type[Any]] = {}
    modules = (
        agents.types,
        domain.types,
        workflows.types,
    )
    for module in modules:
        for _name, value in inspect.getmembers(module, inspect.isclass):
            if value.__module__ == module.__name__ and (
                dataclasses.is_dataclass(value) or issubclass(value, Enum)
            ):
                registry[f"{value.__module__}.{value.__qualname__}"] = value
    for value in (InMemoryWorkflowStore, InMemoryLedgerBinding, Ledger, TenantWorkspace):
        registry[f"{value.__module__}.{value.__qualname__}"] = value
    return registry


_TRUSTED_CLASSES = _trusted_classes()


class _Encoder:
    def __init__(self) -> None:
        self._object_ids: dict[int, int] = {}
        self._nodes: list[dict[str, Any]] = []

    def encode(self, value: Any) -> dict[str, Any]:
        root = self._encode(value)
        return {"root": root, "nodes": self._nodes}

    def _encode(self, value: Any) -> Any:
        if isinstance(value, Enum):
            class_name = f"{type(value).__module__}.{type(value).__qualname__}"
            if class_name not in _TRUSTED_CLASSES:
                raise TypeError(f"unsupported session enum: {class_name}")
            return {"$enum": class_name, "value": value.value}
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Decimal):
            return {"$decimal": str(value)}
        if isinstance(value, datetime):
            return {"$datetime": value.isoformat()}
        if isinstance(value, date):
            return {"$date": value.isoformat()}
        if isinstance(value, Path):
            return {"$path": str(value)}
        if isinstance(value, bytes):
            raise TypeError("bytes are not supported in workflow operator sessions")

        object_id = id(value)
        if object_id in self._object_ids:
            return {"$ref": self._object_ids[object_id]}
        ref = len(self._nodes)
        self._object_ids[object_id] = ref
        self._nodes.append({})

        if isinstance(value, dict):
            node = {
                "kind": "dict",
                "items": [[self._encode(k), self._encode(v)] for k, v in value.items()],
            }
        elif isinstance(value, list):
            node = {"kind": "list", "items": [self._encode(item) for item in value]}
        elif isinstance(value, tuple):
            node = {"kind": "tuple", "items": [self._encode(item) for item in value]}
        elif isinstance(value, (set, frozenset)):
            node = {
                "kind": "frozenset" if isinstance(value, frozenset) else "set",
                "items": [self._encode(item) for item in value],
            }
        else:
            class_name = f"{type(value).__module__}.{type(value).__qualname__}"
            if class_name not in _TRUSTED_CLASSES:
                raise TypeError(f"unsupported session object: {class_name}")
            if isinstance(value, InMemoryWorkflowStore):
                state = value.__getstate__()
            elif hasattr(value, "__dict__"):
                state = dict(value.__dict__)
            else:
                state = {
                    field.name: getattr(value, field.name) for field in dataclasses.fields(value)
                }
            node = {"kind": "object", "class": class_name, "state": self._encode(state)}

        self._nodes[ref] = node
        return {"$ref": ref}


class _Decoder:
    def __init__(self, nodes: Any) -> None:
        if not isinstance(nodes, list):
            raise SessionFormatError("session nodes must be a list")
        self._nodes = nodes
        self._objects: list[Any] = [None] * len(nodes)
        self._building: set[int] = set()

    def decode(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if not isinstance(value, dict):
            raise SessionFormatError("invalid encoded session value")
        if "$decimal" in value:
            return Decimal(str(value["$decimal"]))
        if "$datetime" in value:
            return datetime.fromisoformat(str(value["$datetime"]))
        if "$date" in value:
            return date.fromisoformat(str(value["$date"]))
        if "$path" in value:
            return Path(str(value["$path"]))
        if "$enum" in value:
            cls = self._class(str(value["$enum"]))
            if not issubclass(cls, Enum):
                raise SessionFormatError("session enum class is not an enum")
            return cls(value["value"])
        if "$ref" in value:
            return self._decode_ref(value["$ref"])
        raise SessionFormatError("unknown encoded session value")

    def _class(self, name: str) -> type[Any]:
        cls = _TRUSTED_CLASSES.get(name)
        if cls is None:
            raise SessionFormatError(f"unsupported session class: {name}")
        return cls

    def _decode_ref(self, raw_ref: Any) -> Any:
        if not isinstance(raw_ref, int) or isinstance(raw_ref, bool):
            raise SessionFormatError("session reference must be an integer")
        if raw_ref < 0 or raw_ref >= len(self._nodes):
            raise SessionFormatError("session reference is out of range")
        if self._objects[raw_ref] is not None:
            return self._objects[raw_ref]
        if raw_ref in self._building:
            cycle_obj = self._objects[raw_ref]
            if cycle_obj is None:
                raise SessionFormatError("unsupported cycle through immutable container")
            return cycle_obj

        node = self._nodes[raw_ref]
        if not isinstance(node, dict):
            raise SessionFormatError("session node must be an object")
        kind = node.get("kind")
        self._building.add(raw_ref)
        try:
            if kind == "dict":
                obj: Any = {}
                self._objects[raw_ref] = obj
                items = node.get("items")
                if not isinstance(items, list):
                    raise SessionFormatError("dictionary items must be a list")
                for pair in items:
                    if not isinstance(pair, list) or len(pair) != 2:
                        raise SessionFormatError("dictionary item must be a key/value pair")
                    obj[self.decode(pair[0])] = self.decode(pair[1])
            elif kind == "list":
                obj = []
                self._objects[raw_ref] = obj
                obj.extend(self.decode(item) for item in self._items(node))
            elif kind in ("tuple", "set", "frozenset"):
                values = [self.decode(item) for item in self._items(node)]
                obj = tuple(values) if kind == "tuple" else set(values)
                if kind == "frozenset":
                    obj = frozenset(values)
                self._objects[raw_ref] = obj
            elif kind == "object":
                cls = self._class(str(node.get("class") or ""))
                obj = object.__new__(cls)
                self._objects[raw_ref] = obj
                state = self.decode(node.get("state"))
                if not isinstance(state, dict):
                    raise SessionFormatError("session object state must be a dictionary")
                for key, item in state.items():
                    if not isinstance(key, str):
                        raise SessionFormatError("session object attribute must be a string")
                    object.__setattr__(obj, key, item)
                if isinstance(obj, InMemoryWorkflowStore):
                    object.__setattr__(obj, "_lock", threading.RLock())
            else:
                raise SessionFormatError(f"unknown session node kind: {kind!r}")
            return obj
        finally:
            self._building.discard(raw_ref)

    @staticmethod
    def _items(node: dict[str, Any]) -> list[Any]:
        items = node.get("items")
        if not isinstance(items, list):
            raise SessionFormatError("container items must be a list")
        return items


def encode_session(payload: dict[str, Any]) -> str:
    graph = _Encoder().encode(payload)
    canonical_graph = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    envelope = {
        "format": SESSION_FORMAT,
        "version": SESSION_VERSION,
        "sha256": hashlib.sha256(canonical_graph.encode("utf-8")).hexdigest(),
        "graph": graph,
    }
    return json.dumps(envelope, indent=2, sort_keys=True) + "\n"


def decode_session(raw: str) -> dict[str, Any]:
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SessionFormatError("workflow session is not valid JSON") from exc
    if not isinstance(envelope, dict):
        raise SessionFormatError("workflow session envelope must be an object")
    if envelope.get("format") != SESSION_FORMAT:
        raise SessionFormatError("unsupported workflow session format")
    if envelope.get("version") != SESSION_VERSION:
        raise SessionFormatError(
            f"unsupported workflow session version: {envelope.get('version')!r}"
        )
    graph = envelope.get("graph")
    canonical_graph = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    expected = hashlib.sha256(canonical_graph.encode("utf-8")).hexdigest()
    if envelope.get("sha256") != expected:
        raise SessionFormatError("workflow session integrity check failed")
    if not isinstance(graph, dict) or "root" not in graph:
        raise SessionFormatError("workflow session graph is malformed")
    payload = _Decoder(graph.get("nodes")).decode(graph["root"])
    if not isinstance(payload, dict):
        raise SessionFormatError("workflow session payload must be a dictionary")
    return payload
