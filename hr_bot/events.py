"""Lightweight event registry — mirrors @on_event(\"employee.created\") pattern in diagram."""

from typing import Any, Callable, Dict, List

_HANDLERS: Dict[str, List[Callable[..., Any]]] = {}


def on_event(name: str):
    def decorator(fn: Callable[..., Any]):
        _HANDLERS.setdefault(name, []).append(fn)
        return fn

    return decorator


def emit(name: str, **payload: Any) -> List[Any]:
    results = []
    for handler in _HANDLERS.get(name, []):
        results.append(handler(**payload))
    return results


def handlers_for(name: str) -> List[Callable[..., Any]]:
    return list(_HANDLERS.get(name, []))
