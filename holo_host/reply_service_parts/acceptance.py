from __future__ import annotations

from typing import Any


def accept_stage10(self: Any, **kwargs: Any) -> dict[str, Any]:
    return _call_method(self, "_accept_stage10_impl", **kwargs)


def accept_stage12(self: Any, **kwargs: Any) -> dict[str, Any]:
    return _call_method(self, "_accept_stage12_impl", **kwargs)


def accept_stage13(self: Any, **kwargs: Any) -> dict[str, Any]:
    return _call_method(self, "_accept_stage13_impl", **kwargs)


def accept_stage14(self: Any, **kwargs: Any) -> dict[str, Any]:
    return _call_method(self, "_accept_stage14_impl", **kwargs)


def accept_stage16(self: Any, **kwargs: Any) -> dict[str, Any]:
    return _call_method(self, "_accept_stage16_impl", **kwargs)


def _call_method(self: Any, method_name: str, **kwargs: Any) -> dict[str, Any]:
    method = getattr(self, method_name)
    return method(**kwargs)
