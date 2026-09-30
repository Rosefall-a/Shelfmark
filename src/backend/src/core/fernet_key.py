from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values


def _app_data_dir() -> Path:
    return Path(os.getenv("APP_DATA_DIR", "/data")).expanduser()


def _paths() -> tuple[Path, Path, Path]:
    config_dir = _app_data_dir() / "config"
    return (
        config_dir / "fernet.key",
        config_dir / "fernet.key.1",
        config_dir / "fernet.key.2",
    )


def _valid_key(value: str) -> bool:
    try:
        Fernet(value.encode("utf-8"))
        return True
    except (ValueError, TypeError):
        return False


def persistent_fernet_key() -> str:
    """Return a stable installation key, generating and persisting it when needed.

    Three copies are maintained so a single damaged/missing copy can be repaired.
    If multiple valid copies disagree, startup fails closed rather than risking
    silent loss of encrypted application secrets.
    """
    paths = _paths()
    env_key = os.getenv("SECRET_KEY", "").strip() or str(dotenv_values(".env").get("SECRET_KEY") or "").strip()

    valid: list[str] = []
    for path in paths:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if _valid_key(value):
            valid.append(value)

    if not valid:
        key = env_key or Fernet.generate_key().decode("utf-8")
    else:
        counts = Counter(valid)
        key, count = counts.most_common(1)[0]
        if len(valid) >= 2 and count < 2:
            raise RuntimeError(
                "Persistent Fernet key copies disagree. Refusing to start; "
                f"restore at least two matching copies in {paths[0].parent}."
            )

    _write_current_key(key, paths)
    return key


def _write_current_key(key: str, paths: tuple[Path, Path, Path]) -> None:
    config_dir = paths[0].parent
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        for path in paths:
            path.write_text(key + "\n", encoding="utf-8")
            path.chmod(0o600)
    except OSError as exc:
        raise RuntimeError(
            f"Could not persist the Fernet key in {config_dir}. "
            "Mount APP_DATA_DIR as a writable persistent volume."
        ) from exc


def restore_persistent_fernet_key(key: str) -> None:
    """Install an exported key while preserving the previous key for recovery."""
    if not _valid_key(key):
        raise ValueError("Invalid Fernet key.")
    paths = _paths()
    old_key = persistent_fernet_key()
    if old_key != key:
        previous_path = paths[0].parent / "fernet.key.previous"
        previous_path.parent.mkdir(parents=True, exist_ok=True)
        previous_path.write_text(old_key + "\n", encoding="utf-8")
        previous_path.chmod(0o600)
    _write_current_key(key, paths)


def rotate_persistent_fernet_key() -> tuple[str, str]:
    """Rotate the installation key and retain the previous key for decryption."""
    paths = _paths()
    old_key = persistent_fernet_key()
    new_key = Fernet.generate_key().decode("utf-8")
    previous_path = paths[0].parent / "fernet.key.previous"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    previous_path.write_text(old_key + "\n", encoding="utf-8")
    previous_path.chmod(0o600)
    _write_current_key(new_key, paths)
    return old_key, new_key


def previous_fernet_key() -> str | None:
    path = _paths()[0].parent / "fernet.key.previous"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if _valid_key(value) else None
