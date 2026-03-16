"""
Nitter API client with TTL-aware caching.

This module is the ONLY place that makes HTTP requests to nitter.net.
All consuming code MUST go through this client to ensure rate limits
and caching policies are respected.

Design principles:
- TTL-aware: Respects expiration times, never fetches if cache valid
- Error-resilient: Different retry/backoff strategies per error type
- Isolated: No other module should make direct HTTP calls to nitter
"""

import sys
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from enum import Enum

import requests
import feedparser

import config
from storage import AccountStorage, FetchMeta, StorageManager


class FetchStatus(Enum):
    """Status of a fetch operation."""
    SUCCESS = "success"
    NETWORK_ERROR = "network_error"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    PARSE_ERROR = "parse_error"


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    success: bool
    status: FetchStatus
    username: str
    feed_data: Optional[bytes]  # Raw XML
    parsed_feed: Optional[Any]  # feedparser result
    meta: Optional[FetchMeta]
    http_status: Optional[int]
    error_message: Optional[str]
    came_from_cache: bool


class NitterClient:
    """
    Client for fetching Twitter RSS feeds from nitter.net.
    
    Usage:
        client = NitterClient()
        result = client.get_feed("elonmusk")
        if result.success:
            print(f"Got {len(result.parsed_feed.entries)} entries")
    """
    
    def __init__(self, respect_ttl: bool = True, force_refresh: bool = False):
        """
        Initialize client.
        
        Args:
            respect_ttl: If True (default), use cache if not expired
            force_refresh: If True, ignore cache and fetch fresh (use sparingly!)
        """
        self.respect_ttl = respect_ttl
        self.force_refresh = force_refresh
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.USER_AGENT,
            'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.1',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
        })
    
    def _build_url(self, username: str) -> str:
        """Build RSS URL for a username."""
        return f"https://{config.NITTER_HOST}/{username}/rss"
    
    def _determine_status(self, http_status: Optional[int], parse_error: bool = False) -> FetchStatus:
        """Determine status category from HTTP status code."""
        if parse_error:
            return FetchStatus.PARSE_ERROR
        if http_status is None:
            return FetchStatus.NETWORK_ERROR
        if http_status == 429:
            return FetchStatus.RATE_LIMITED
        if 500 <= http_status < 600:
            return FetchStatus.SERVER_ERROR
        if 400 <= http_status < 500:
            return FetchStatus.CLIENT_ERROR
        if 200 <= http_status < 300:
            return FetchStatus.SUCCESS
        return FetchStatus.NETWORK_ERROR
    
    def _calculate_expiry(self, status: FetchStatus, http_status: Optional[int] = None) -> datetime:
        """Calculate expiry time based on status."""
        ttl = config.TTL.get_for_status(http_status, status == FetchStatus.PARSE_ERROR)
        return datetime.now(timezone.utc) + timedelta(seconds=ttl)
    
    def _try_cache(self, username: str) -> Optional[FetchResult]:
        """Try to get valid cached result. Returns None if no valid cache."""
        if self.force_refresh:
            return None
        
        storage = StorageManager.get_account(username)
        cached = storage.get_latest()
        
        if cached is None:
            return None
        
        feed_path, meta = cached
        
        if self.respect_ttl and not meta.is_expired():
            # Valid cache hit (success OR error/backoff)
            if feed_path is None:
                # Cached error/backoff entry
                status = FetchStatus(meta.status) if meta.status else FetchStatus.NETWORK_ERROR
                return FetchResult(
                    success=False,
                    status=status,
                    username=username,
                    feed_data=None,
                    parsed_feed=None,
                    meta=meta,
                    http_status=meta.http_status,
                    error_message=meta.error_message,
                    came_from_cache=True,
                )

            feed_data = feed_path.read_bytes()
            parsed = feedparser.parse(feed_data)

            return FetchResult(
                success=True,
                status=FetchStatus.SUCCESS,
                username=username,
                feed_data=feed_data,
                parsed_feed=parsed,
                meta=meta,
                http_status=meta.http_status,
                error_message=None,
                came_from_cache=True,
            )
        
        # Cache exists but expired
        return None
    
    def _do_fetch(self, username: str) -> FetchResult:
        """
        Actually perform HTTP fetch from nitter.net.
        This is the ONLY method that makes external HTTP calls.
        """
        url = self._build_url(username)
        storage = StorageManager.get_account(username)
        
        now = datetime.now(timezone.utc)
        http_status: Optional[int] = None
        feed_data: Optional[bytes] = None
        parsed_feed: Optional[Any] = None
        error_message: Optional[str] = None
        parse_error = False
        
        try:
            response = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            http_status = response.status_code
            response.raise_for_status()
            feed_data = response.content
            
            # Try to parse
            parsed_feed = feedparser.parse(feed_data)
            
            # Check if it's actually valid RSS
            if not hasattr(parsed_feed, 'entries') or parsed_feed.bozo:
                parse_error = True
                error_message = f"Invalid RSS: {getattr(parsed_feed, 'bozo_exception', 'unknown')}"
            
        except requests.exceptions.Timeout:
            error_message = "Request timed out"
        except requests.exceptions.ConnectionError as e:
            error_message = f"Connection error: {e}"
        except requests.exceptions.HTTPError as e:
            error_message = f"HTTP error: {e}"
        except requests.exceptions.RequestException as e:
            error_message = f"Request failed: {e}"
        except Exception as e:
            error_message = f"Unexpected error: {e}"
        
        # Determine status
        status = self._determine_status(http_status, parse_error)
        success = status == FetchStatus.SUCCESS
        
        # Build metadata
        expires_at = self._calculate_expiry(status, http_status)
        
        meta = FetchMeta(
            username=username,
            fetched_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
            status=status.value,
            http_status=http_status,
            error_type=status.value if not success else None,
            error_message=error_message if not success else None,
            entry_count=len(parsed_feed.entries) if parsed_feed and hasattr(parsed_feed, 'entries') else 0,
            ttl_seconds=int((expires_at - now).total_seconds()),
            feed_path="",  # Will be set by storage
        )
        
        # Save meta always (cache errors briefly for backoff); save feed only on success
        storage.save_result(feed_data if success else None, meta)
        
        return FetchResult(
            success=success,
            status=status,
            username=username,
            feed_data=feed_data if success else None,
            parsed_feed=parsed_feed if success else None,
            meta=meta,
            http_status=http_status,
            error_message=error_message,
            came_from_cache=False,
        )
    
    def get_feed(self, username: str) -> FetchResult:
        """
        Get RSS feed for a username.
        
        This is the main entry point. It will:
        1. Check cache first (if respect_ttl=True and not force_refresh)
        2. Fetch from nitter.net if needed
        3. Cache successful responses
        4. Return result with metadata
        
        Args:
            username: Twitter username (without @)
        
        Returns:
            FetchResult with all details
        """
        username = username.lower().strip()
        
        # Try cache first
        cached = self._try_cache(username)
        if cached:
            return cached
        
        # Fetch fresh
        return self._do_fetch(username)
    
    def peek_cache(self, username: str) -> Optional[FetchMeta]:
        """
        Check cache status without fetching.
        Returns metadata if cache exists, None otherwise.
        """
        username = username.lower().strip()
        storage = StorageManager.get_account(username)
        cached = storage.get_latest()
        return cached[1] if cached else None
    
    def clear_cache(self, username: str) -> bool:
        """Clear cache for a specific account. Returns True if cache existed."""
        storage = StorageManager.get_account(username)
        latest = storage._get_latest_link_path()
        if latest.exists():
            latest.unlink()
            return True
        return False


# Convenience function for simple use cases
def get_feed(username: str, force: bool = False) -> FetchResult:
    """
    Simple function to get a feed with default settings.
    
    Args:
        username: Twitter username
        force: If True, bypass cache and fetch fresh
    
    Returns:
        FetchResult
    """
    client = NitterClient(respect_ttl=True, force_refresh=force)
    return client.get_feed(username)


if __name__ == "__main__":
    # CLI for testing
    if len(sys.argv) < 2:
        print("Usage: python nitter_client.py <username> [--force]")
        sys.exit(1)
    
    username = sys.argv[1]
    force = "--force" in sys.argv
    
    result = get_feed(username, force=force)
    
    print(f"\n{'='*50}")
    print(f"Username: @{result.username}")
    print(f"Success: {result.success}")
    print(f"Status: {result.status.value}")
    print(f"From cache: {result.came_from_cache}")
    
    if result.http_status:
        print(f"HTTP status: {result.http_status}")
    
    if result.error_message:
        print(f"Error: {result.error_message}")
    
    if result.success and result.parsed_feed:
        print(f"Entries: {len(result.parsed_feed.entries)}")
        print(f"Feed title: {result.parsed_feed.feed.get('title', 'N/A')}")
        
        if result.meta:
            print(f"Expires at: {result.meta.expires_at}")
    
    print(f"{'='*50}")
