"""Persistent dataset identities and independent SQLite ledgers; no active-profile global."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from uuid import uuid4

from .models import DEFAULT_KNOWN, DEFAULT_VALID, QueryRequest, now, timestamp
from .store import Store

PROFILE_PATTERN = re.compile(r"(?:demo|p-[0-9a-f]{32})\Z")
IMPORT_FORMATS = ["pdf", "txt", "md", "json", "jsonl", "csv"]


class ProfileManager:
    def __init__(self, demo_path):
        self.demo_path = Path(demo_path).resolve()
        self.directory = self.demo_path.parent / "profiles"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._catalog = sqlite3.connect(self.directory / "catalog.sqlite3", check_same_thread=False, timeout=15)
        self._catalog.row_factory = sqlite3.Row
        self._catalog.execute("PRAGMA journal_mode=WAL")
        self._catalog.execute("PRAGMA foreign_keys=ON")
        self._catalog.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at TEXT NOT NULL, is_demo INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS previews (
                id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES profiles(id),
                content_hash TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(profile_id,content_hash)
            );
        """)
        with self._catalog:
            self._catalog.execute("INSERT OR IGNORE INTO profiles VALUES ('demo','Chronoverse Demo',?,1)", (now(),))
        self._stores = {}
        self.get_store("demo")

    def close(self):
        with self._lock:
            for store in self._stores.values():
                store.close()
            self._stores.clear()
            self._catalog.close()

    def _profile(self, profile_id):
        if not isinstance(profile_id, str) or not PROFILE_PATTERN.fullmatch(profile_id):
            raise ValueError("Invalid profile_id; expected demo or p- followed by 32 hexadecimal digits")
        row = self._catalog.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            raise KeyError("Dataset profile not found")
        return {"id":row["id"], "name":row["name"], "created_at":row["created_at"], "is_demo":bool(row["is_demo"])}

    def get_profile(self, profile_id):
        with self._lock:
            return self._profile(profile_id)

    def get_store(self, profile_id="demo"):
        with self._lock:
            self._profile(profile_id)
            if profile_id not in self._stores:
                path = self.demo_path if profile_id == "demo" else self.directory / f"{profile_id}.sqlite3"
                self._stores[profile_id] = Store(path, seed=profile_id == "demo")
            return self._stores[profile_id]

    def list_profiles(self):
        with self._lock:
            ids = [row[0] for row in self._catalog.execute("SELECT id FROM profiles ORDER BY is_demo DESC,created_at,id")]
            result = []
            for profile_id in ids:
                profile = self._profile(profile_id)
                # Catalog counts are inventory counts, including explicitly imported future vintages.
                store = self.get_store(profile_id)
                with store._lock:
                    profile["counts"] = {table:store._db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("assertions","events")}
                result.append(profile)
            return result

    def create_profile(self, name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Profile name must contain 1–100 characters")
        name = name.strip()
        profile_id = "p-" + uuid4().hex
        with self._lock, self._catalog:
            self._catalog.execute("BEGIN IMMEDIATE")
            if self._catalog.execute("SELECT 1 FROM profiles WHERE name=? COLLATE NOCASE", (name,)).fetchone():
                raise ValueError("A profile with this name already exists")
            if self._catalog.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] >= 100:
                raise ValueError("Maximum 100 dataset profiles reached")
            self._catalog.execute("INSERT INTO profiles VALUES (?,?,?,0)", (profile_id,name,now()))
        store = self.get_store(profile_id)
        profile = self.get_profile(profile_id)
        profile["counts"] = {"assertions":0,"events":0}
        return profile

    def default_scope(self, profile_id="demo"):
        self.get_profile(profile_id)
        current = now()
        return {"valid_at":DEFAULT_VALID if profile_id == "demo" else current,
                "known_at":DEFAULT_KNOWN if profile_id == "demo" else current,
                "world":"main", "plane":"all", "perspective":"all"}

    def query(self, profile_id, request):
        request = request if isinstance(request, QueryRequest) else QueryRequest.model_validate(request)
        data = request.model_dump()
        defaults = self.default_scope(profile_id)
        for key in ("valid_at","known_at"):
            if key not in request.model_fields_set:
                data[key] = defaults[key]
        return {**self.get_store(profile_id).query(QueryRequest(**data)), "profile_id":profile_id}

    def meta(self, profile_id="demo", known_at=None):
        defaults = self.default_scope(profile_id)
        value = self.get_store(profile_id).meta(known_at=known_at or defaults["known_at"])
        value.update(profile_id=profile_id, profile=self.get_profile(profile_id), defaults=defaults, import_formats=IMPORT_FORMATS)
        if profile_id != "demo":
            value["examples"] = []
            # Empty profiles still have usable scope controls for their first upload.
            value["worlds"] = value["worlds"] or ["main"]
            value["perspectives"] = value["perspectives"] or ["general"]
        return value
