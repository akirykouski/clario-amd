"""Encrypted patient store.

Key = Argon2id(passphrase, random salt). Every record is AES-256-GCM encrypted as a whole JSON
document, including dates, so the database file reveals only record counts and kinds.
There is no recovery: a lost passphrase means the data is gone, by design.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CHECK = b"clario-vault-v1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, kind TEXT NOT NULL, blob BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS ix_kind ON records(kind);
"""


class Locked(RuntimeError):
    pass


class BadPassphrase(RuntimeError):
    pass


def derive_key(passphrase: str, salt: bytes) -> bytes:
    # OWASP-recommended Argon2id parameters (m=64 MiB, t=3, p=4)
    return hash_secret_raw(passphrase.encode(), salt, time_cost=3, memory_cost=65536, parallelism=4,
                           hash_len=32, type=Type.ID)


class Vault:
    def __init__(self, data_dir: Path, auto_lock_minutes: int = 15):
        data_dir.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(data_dir / "clario.db", check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._key: AESGCM | None = None
        self._last_use = 0.0
        self._ttl = auto_lock_minutes * 60

    # ------------------------------------------------------------ state
    def _meta(self, k: str) -> bytes | None:
        with self._lock:
            r = self._db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else None

    @property
    def initialized(self) -> bool:
        return self._meta("salt") is not None

    @property
    def locked(self) -> bool:
        if self._key and self._ttl and time.monotonic() - self._last_use > self._ttl:
            self.lock()
        return self._key is None

    def setup(self, passphrase: str) -> None:
        if self.initialized:
            raise ValueError("vault already initialized")
        if len(passphrase) < 12:
            raise ValueError("passphrase must be at least 12 characters")
        salt = os.urandom(16)
        key = AESGCM(derive_key(passphrase, salt))
        with self._lock:
            self._db.execute("INSERT INTO meta VALUES ('salt', ?)", (salt,))
            self._db.execute("INSERT INTO meta VALUES ('check', ?)", (self._seal(key, CHECK),))
            self._db.commit()
        self._key, self._last_use = key, time.monotonic()

    def unlock(self, passphrase: str) -> None:
        salt, check = self._meta("salt"), self._meta("check")
        if salt is None or check is None:
            raise ValueError("vault not initialized")
        key = AESGCM(derive_key(passphrase, salt))
        try:
            if self._open(key, check) != CHECK:
                raise BadPassphrase()
        except InvalidTag as e:
            raise BadPassphrase() from e
        self._key, self._last_use = key, time.monotonic()

    def lock(self) -> None:
        self._key = None

    # ------------------------------------------------------------ crypto
    @staticmethod
    def _seal(key: AESGCM, data: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + key.encrypt(nonce, data, None)

    @staticmethod
    def _open(key: AESGCM, blob: bytes) -> bytes:
        return key.decrypt(blob[:12], blob[12:], None)

    def _k(self) -> AESGCM:
        if self.locked:
            raise Locked()
        self._last_use = time.monotonic()
        return self._key  # type: ignore[return-value]

    # ------------------------------------------------------------ records
    def put(self, kind: str, rid: str, doc: dict[str, Any]) -> None:
        blob = self._seal(self._k(), json.dumps(doc, ensure_ascii=False).encode())
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (rid, kind, blob))
            self._db.commit()

    def get(self, rid: str) -> dict[str, Any] | None:
        k = self._k()
        with self._lock:  # one connection shared by the thread pool: reads must not interleave with writes
            r = self._db.execute("SELECT blob FROM records WHERE id=?", (rid,)).fetchone()
        return json.loads(self._open(k, r[0])) if r else None

    def all(self, kind: str) -> list[dict[str, Any]]:
        k = self._k()
        with self._lock:
            rows = self._db.execute("SELECT blob FROM records WHERE kind=?", (kind,)).fetchall()
        return [json.loads(self._open(k, r[0])) for r in rows]

    def delete(self, rid: str) -> None:
        self._k()
        with self._lock:
            self._db.execute("DELETE FROM records WHERE id=?", (rid,))
            self._db.commit()

    def raw_file(self) -> bytes:
        """For tests: the on-disk database bytes."""
        with self._lock:
            self._db.commit()
        return Path(self._db.execute("PRAGMA database_list").fetchone()[2]).read_bytes()
