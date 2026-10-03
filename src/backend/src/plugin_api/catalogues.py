"""Persistent catalogue configuration, separate from package-signature trust."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


class CatalogueStoreError(ValueError):
    """Raised when catalogue configuration cannot be safely read or changed."""


class CatalogueStore:
    """Small atomic JSON store for administrator-managed catalogue endpoints."""

    def __init__(self, path: Path, official_url: str) -> None:
        self.path = path
        self.official_url = official_url
        self._lock = threading.Lock()

    def _official(self) -> dict[str, Any]:
        return {
            "id": "official",
            "name": "Official catalogue",
            "url": self.official_url,
            "enabled": True,
            "priority": 0,
            "trust_metadata": {
                "provenance": "official",
                "package_signature_trust": "independent",
            },
            "last_successful_check": None,
            "last_error": None,
        }

    def _read(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [self._official()]
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogueStoreError("catalogue configuration cannot be read") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise CatalogueStoreError("catalogue configuration has an unsupported schema")
        records = payload.get("catalogues")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise CatalogueStoreError("catalogue configuration is invalid")
        by_id = {str(item.get("id")): dict(item) for item in records if item.get("id")}
        official = self._official()
        if "official" in by_id:
            official.update(
                {
                    "enabled": bool(by_id["official"].get("enabled", True)),
                    "last_successful_check": by_id["official"].get("last_successful_check"),
                    "last_error": by_id["official"].get("last_error"),
                }
            )
        by_id["official"] = official
        return sorted(by_id.values(), key=lambda item: (int(item.get("priority", 100)), item["id"]))

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "catalogues": records}, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read()

    def add(self, *, name: str, url: str, enabled: bool, priority: int) -> dict[str, Any]:
        with self._lock:
            records = self._read()
            if any(item["url"] == url for item in records):
                raise CatalogueStoreError("catalogue URL is already configured")
            record = {
                "id": str(uuid4()),
                "name": name,
                "url": url,
                "enabled": enabled,
                "priority": priority,
                "trust_metadata": {
                    "provenance": "administrator-configured",
                    "package_signature_trust": "independent",
                },
                "last_successful_check": None,
                "last_error": None,
            }
            records.append(record)
            self._write(records)
            return record

    def update(self, catalogue_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            records = self._read()
            record = next((item for item in records if item["id"] == catalogue_id), None)
            if record is None:
                raise CatalogueStoreError("catalogue not found")
            if catalogue_id == "official":
                changes = {
                    key: value
                    for key, value in changes.items()
                    if key in {"enabled", "last_successful_check", "last_error"}
                }
            record.update(changes)
            self._write(records)
            return record

    def remove(self, catalogue_id: str) -> None:
        if catalogue_id == "official":
            raise CatalogueStoreError("the official catalogue cannot be removed")
        with self._lock:
            records = self._read()
            filtered = [item for item in records if item["id"] != catalogue_id]
            if len(filtered) == len(records):
                raise CatalogueStoreError("catalogue not found")
            self._write(filtered)

    def record_check(self, catalogue_id: str, error: str | None) -> None:
        if error is None:
            self.update(
                catalogue_id,
                last_successful_check=int(time.time()),
                last_error=None,
            )
            return
        self.update(catalogue_id, last_error=error)


__all__ = ["CatalogueStore", "CatalogueStoreError"]
