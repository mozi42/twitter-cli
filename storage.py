"""File-based storage for cached feeds.

Organizes data as:
~/.cache/twitter-cli/accounts/
└── {username}/
    ├── 20260315-184522/       # Timestamped directory
    │   ├── feed.xml           # Raw RSS (only for successful fetches)
    │   └── meta.json          # Metadata (always written)
    └── latest.json            # Pointer to most recent (success OR error)

Design:
- Successful fetch: save feed.xml + meta.json, update latest.json
- Failed fetch: save meta.json only, update latest.json
  This allows TTL-based backoff on repeated failures.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass, asdict

import config

# Ensure directories exist on import
config.ensure_dirs()


@dataclass
class FetchMeta:
    """Metadata for a fetch operation."""

    username: str
    fetched_at: str  # ISO timestamp
    expires_at: str  # ISO timestamp
    status: str
    http_status: Optional[int]
    error_type: Optional[str]
    error_message: Optional[str]
    entry_count: int
    ttl_seconds: int
    feed_path: str  # relative path to feed.xml; "" when no feed stored

    def is_expired(self) -> bool:
        """Check if this cached entry has expired."""
        try:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > expires
        except Exception:
            return True


class AccountStorage:
    """Manages storage for a single account."""

    def __init__(self, username: str):
        self.username = username.lower().strip()
        self.base_dir = config.ACCOUNTS_DIR / self.username
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_latest_link_path(self) -> Path:
        return self.base_dir / "latest.json"

    def save_result(self, feed_data: Optional[bytes], meta: FetchMeta) -> Optional[Path]:
        """Save a fetch result.

        Always writes meta.json and updates latest.json.
        Writes feed.xml only when feed_data is provided.

        Returns:
            Path to feed.xml if written, else None.
        """

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        fetch_dir = self.base_dir / timestamp
        fetch_dir.mkdir(exist_ok=True)

        feed_path: Optional[Path] = None
        if feed_data is not None:
            feed_path = fetch_dir / "feed.xml"
            feed_path.write_bytes(feed_data)
            meta.feed_path = str(feed_path.relative_to(self.base_dir))
        else:
            meta.feed_path = ""

        meta_path = fetch_dir / "meta.json"
        meta_path.write_text(json.dumps(asdict(meta), indent=2))

        pointer = {"timestamp": timestamp, "meta": asdict(meta)}
        self._get_latest_link_path().write_text(json.dumps(pointer, indent=2))

        return feed_path

    def save_fetch(self, feed_data: bytes, meta: FetchMeta) -> Path:
        """Back-compat wrapper for successful fetches."""
        p = self.save_result(feed_data, meta)
        assert p is not None
        return p

    def get_latest(self) -> Optional[Tuple[Optional[Path], FetchMeta]]:
        """Get the latest cached result (success or error)."""

        link_path = self._get_latest_link_path()
        if not link_path.exists():
            return None

        try:
            pointer = json.loads(link_path.read_text())
            timestamp = pointer["timestamp"]
            meta_dict = pointer["meta"]

            fetch_dir = self.base_dir / timestamp
            feed_path = fetch_dir / "feed.xml"

            meta = FetchMeta(**meta_dict)
            if feed_path.exists():
                return (feed_path, meta)

            # Meta-only (cached error/backoff)
            return (None, meta)
        except Exception:
            return None

    def get_feed_content(self) -> Optional[bytes]:
        latest = self.get_latest()
        if not latest:
            return None
        feed_path, _ = latest
        if feed_path is None:
            return None
        return feed_path.read_bytes()

    def list_fetches(self, limit: int = 100) -> List[dict]:
        """List fetch history for this account."""
        fetches: List[dict] = []

        for item in sorted(self.base_dir.iterdir(), reverse=True):
            if item.is_dir() and item.name != "__pycache__":
                meta_path = item / "meta.json"
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text())
                        meta["timestamp"] = item.name
                        meta["expired"] = FetchMeta(**meta).is_expired()
                        fetches.append(meta)
                    except Exception:
                        pass

        return fetches[:limit]

    def clean_old(self, keep: int = 10) -> int:
        """Remove old fetch directories, keeping N most recent."""
        fetches = []
        for item in self.base_dir.iterdir():
            if item.is_dir():
                fetches.append((item.stat().st_mtime, item))

        fetches.sort(reverse=True)
        removed = 0
        for _, path in fetches[keep:]:
            shutil.rmtree(path)
            removed += 1
        return removed


class StorageManager:
    """Factory for AccountStorage instances."""

    _cache: dict[str, AccountStorage] = {}

    @classmethod
    def get_account(cls, username: str) -> AccountStorage:
        username = username.lower().strip()
        if username not in cls._cache:
            cls._cache[username] = AccountStorage(username)
        return cls._cache[username]

    @classmethod
    def list_accounts(cls) -> List[str]:
        if not config.ACCOUNTS_DIR.exists():
            return []

        accounts: List[str] = []
        for item in config.ACCOUNTS_DIR.iterdir():
            if item.is_dir() and (item / "latest.json").exists():
                accounts.append(item.name)

        return sorted(accounts)
