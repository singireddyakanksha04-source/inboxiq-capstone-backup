"""Feature discovery.

Every package under ``app/features/`` that exposes a ``router`` is mounted
automatically. Deleting a feature folder removes its endpoints and nothing else
— no import in main.py to clean up, no other feature breaks.

Rule that keeps it true: features never import each other. Shared code lives in
``app/services`` and ``app/models``.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass

from fastapi import APIRouter

import app.features as features_pkg


@dataclass
class Feature:
    name: str
    router: APIRouter


def discover() -> list[Feature]:
    found: list[Feature] = []
    for mod in pkgutil.iter_modules(features_pkg.__path__):
        if not mod.ispkg or mod.name.startswith("_"):
            continue
        package = importlib.import_module(f"{features_pkg.__name__}.{mod.name}")
        router = getattr(package, "router", None)
        if isinstance(router, APIRouter):
            found.append(Feature(name=mod.name, router=router))
    return sorted(found, key=lambda f: f.name)
