from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from kernel_v3.contracts import JsonObject, ToolManifest


OPENAI_NATIVE_TOOL_SURFACE_SCHEMA = "holo.kernel_v3.openai_native_tool_surface.v1"
_NATIVE_TOOL_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_NATIVE_TOOL_NAME_CHARS = 64


@dataclass(frozen=True)
class ProviderNativeToolSurface:
    tools: list[JsonObject]
    name_map: dict[str, str]
    schema: str = OPENAI_NATIVE_TOOL_SURFACE_SCHEMA

    def to_parameters(self) -> JsonObject:
        return {
            "native_tool_surface_schema": self.schema,
            "native_tools": [dict(tool) for tool in self.tools],
            "native_tool_name_map": dict(self.name_map),
        }


def openai_native_tool_surface(
    manifests: Iterable[ToolManifest],
    *,
    allowed_tool_names: set[str] | None = None,
    max_tools: int | None = None,
) -> ProviderNativeToolSurface:
    allowed = set(allowed_tool_names or set())
    tools: list[JsonObject] = []
    name_map: dict[str, str] = {}
    for manifest in sorted(manifests, key=lambda item: item.name):
        if allowed and manifest.name not in allowed:
            continue
        if not manifest.enabled or manifest.name.startswith("__"):
            continue
        native_name = _native_tool_name(manifest.name)
        if native_name in name_map and name_map[native_name] != manifest.name:
            native_name = _native_tool_name(manifest.name, force_hash=True)
        tools.append(_openai_tool_for_manifest(manifest, native_name=native_name))
        name_map[native_name] = manifest.name
        if max_tools is not None and len(tools) >= max(0, int(max_tools)):
            break
    return ProviderNativeToolSurface(tools=tools, name_map=name_map)


def resolve_native_tool_name(name: str, name_map: dict[str, str] | JsonObject | None) -> str:
    if not isinstance(name_map, dict):
        return name
    value = name_map.get(name)
    return str(value) if isinstance(value, str) and value else name


def _openai_tool_for_manifest(manifest: ToolManifest, *, native_name: str) -> JsonObject:
    return {
        "type": "function",
        "function": {
            "name": native_name,
            "description": _tool_description(manifest),
            "parameters": _json_schema_for_input_schema(manifest.input_schema),
        },
    }


def _native_tool_name(tool_name: str, *, force_hash: bool = False) -> str:
    digest = hashlib.sha256(tool_name.encode("utf-8")).hexdigest()[:8]
    slug = _NATIVE_TOOL_NAME_RE.sub("_", tool_name).strip("_")
    slug = re.sub(r"_+", "_", slug) or "tool"
    needs_hash = force_hash or slug != tool_name or len(slug) > _MAX_NATIVE_TOOL_NAME_CHARS
    if not needs_hash:
        return slug
    suffix = "_" + digest
    max_base = max(1, _MAX_NATIVE_TOOL_NAME_CHARS - len(suffix))
    return (slug[:max_base].rstrip("_") or "tool") + suffix


def _tool_description(manifest: ToolManifest) -> str:
    pieces = [
        f"Holo tool: {manifest.name}.",
        str(manifest.description or f"{manifest.resource_kind}.{manifest.operator_kind}").strip(),
        f"Side effect class: {manifest.side_effect_class}.",
    ]
    if manifest.permissions_required:
        pieces.append("Permissions: " + ", ".join(manifest.permissions_required) + ".")
    return " ".join(piece for piece in pieces if piece).strip()[:1024]


def _json_schema_for_input_schema(input_schema: JsonObject) -> JsonObject:
    properties: JsonObject = {}
    required: list[str] = []
    for key, raw_spec in sorted(input_schema.items()):
        name = str(key)
        if name.startswith("_") or name in {"concurrency_safe", "network_fetch_cost_field", "default_network_fetch_cost"}:
            continue
        spec = _schema_spec(raw_spec)
        properties[name] = _json_schema_property(spec)
        if bool(spec.get("required")):
            required.append(name)
    schema: JsonObject = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return schema


def _schema_spec(raw_spec: object) -> JsonObject:
    if isinstance(raw_spec, dict):
        aliases = raw_spec.get("aliases")
        return {
            "type": str(raw_spec.get("type", "object")),
            "required": bool(raw_spec.get("required", True)),
            "min_length": raw_spec.get("min_length"),
            "min": raw_spec.get("min"),
            "max": raw_spec.get("max"),
            "description": raw_spec.get("description"),
            "aliases": [str(item) for item in aliases] if isinstance(aliases, list) else [],
        }
    text = str(raw_spec)
    return {
        "type": text.split()[0],
        "required": "optional" not in text,
        "min_length": None,
        "min": None,
        "max": None,
        "description": None,
        "aliases": [],
    }


def _json_schema_property(spec: JsonObject) -> JsonObject:
    declared_type = str(spec.get("type") or "object")
    prop: JsonObject = _json_type_for_declared_type(declared_type)
    description = spec.get("description")
    aliases = spec.get("aliases")
    if isinstance(description, str) and description:
        prop["description"] = description
    elif isinstance(aliases, list) and aliases:
        prop["description"] = "Aliases accepted by host payload canonicalization: " + ", ".join(str(item) for item in aliases)
    min_length = _optional_int(spec.get("min_length"))
    if min_length is not None and prop.get("type") == "string":
        prop["minLength"] = min_length
    minimum = _optional_number(spec.get("min"))
    if minimum is not None and prop.get("type") in {"integer", "number"}:
        prop["minimum"] = minimum
    maximum = _optional_number(spec.get("max"))
    if maximum is not None and prop.get("type") in {"integer", "number"}:
        prop["maximum"] = maximum
    return prop


def _json_type_for_declared_type(declared_type: str) -> JsonObject:
    lowered = declared_type.strip().lower()
    if lowered in {"str", "string"}:
        return {"type": "string"}
    if lowered in {"int", "integer"}:
        return {"type": "integer"}
    if lowered in {"float", "number", "decimal"}:
        return {"type": "number"}
    if lowered in {"bool", "boolean"}:
        return {"type": "boolean"}
    if lowered in {"object", "dict", "jsonobject"}:
        return {"type": "object", "additionalProperties": True}
    if lowered.startswith("list[") or lowered in {"list", "array"}:
        return {"type": "array", "items": _array_item_schema(lowered)}
    return {"type": "object", "additionalProperties": True}


def _array_item_schema(declared_type: str) -> JsonObject:
    if not declared_type.startswith("list[") or not declared_type.endswith("]"):
        return {}
    inner = declared_type[5:-1].strip().lower()
    if inner in {"str", "string"}:
        return {"type": "string"}
    if inner in {"int", "integer"}:
        return {"type": "integer"}
    if inner in {"float", "number", "decimal"}:
        return {"type": "number"}
    if inner in {"bool", "boolean"}:
        return {"type": "boolean"}
    return {"type": "object", "additionalProperties": True}


def _optional_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _optional_number(value: object) -> int | float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed.is_integer():
        return int(parsed)
    return parsed
