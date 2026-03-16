#!/usr/bin/env python3
"""
Twitter RSS Fetcher - Simple CLI

Usage: twitter-cli <username> [options]

Examples:
  twitter-cli elonmusk           # Get tweets (cached or fresh)
  twitter-cli elonmusk --force   # Force fresh fetch
  twitter-cli elonmusk --json    # Output as JSON
  twitter-cli elonmusk --since 2026-03-15T10:00:00  # Only tweets after time
"""

import sys
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# Add project directory to path for imports (resolve symlinks for robustness)
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from nitter_client import NitterClient, get_feed
from storage import StorageManager, FetchMeta
from query import query_tweets, get_cache_timestamp


def format_relative_time(dt: datetime) -> str:
    """Show relative time (e.g., '5 minutes ago')."""
    now = datetime.now(timezone.utc)
    diff = now - dt
    
    seconds = diff.total_seconds()
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    else:
        return f"{int(seconds // 86400)}d ago"


def strip_html(html: str) -> str:
    """Strip HTML tags and clean up text."""
    text = re.sub(r'<[^>]+>', '', html)
    text = text.replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
    text = text.replace('\n', ' ').replace('  ', ' ').strip()
    return text


def get_tweets(username: str, force: bool = False):
    """
    Get tweets for a user. Returns from cache if valid, otherwise fetches.
    
    Returns: (tweets_list, came_from_cache, meta)
    """
    client = NitterClient(respect_ttl=not force, force_refresh=force)
    result = client.get_feed(username)
    
    if not result.success or not result.parsed_feed:
        # Preserve cache/fresh signal even on error.
        return [], result.came_from_cache, result.meta if hasattr(result, 'meta') else None
    
    tweets = []
    for entry in result.parsed_feed.entries:
        title = entry.get('title', '')
        is_rt = title.startswith("RT by ")
        is_reply = title.startswith("R to ")
        
        author = entry.get('dc_creator', '') or entry.get('author', '')
        if not author and is_rt:
            author = title.split(":")[0].replace("RT by ", "") if ":" in title else ""
        
        pub_date = None
        if 'published' in entry:
            from email.utils import parsedate_to_datetime
            try:
                pub_date = parsedate_to_datetime(entry['published'])
            except:
                pass
        
        if not pub_date:
            pub_date = datetime.now(timezone.utc)
        
        tweets.append({
            'id': entry.get('guid', entry.get('id', '')),
            'text': strip_html(entry.get('description', '')),
            'raw_html': entry.get('description', ''),
            'author': author.lstrip('@'),
            'pub_date': pub_date,
            'url': entry.get('link', ''),
            'is_retweet': is_rt,
            'is_reply': is_reply,
        })
    
    return tweets, result.came_from_cache, result.meta


def filter_since(tweets: list, since: datetime) -> list:
    """Filter tweets to only those after 'since' timestamp."""
    # Ensure since is timezone-aware
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return [t for t in tweets if t['pub_date'] > since]


def main():
    args = sys.argv[1:]
    
    if not args or args[0] in ('-h', '--help', 'help'):
        print(__doc__)
        return 0
    
    username = args[0].lstrip('@')
    
    # Parse options
    force = '--force' in args
    as_json = '--json' in args
    no_rt = '--no-rt' in args
    
    # Parse --since if provided
    since = None
    if '--since' in args:
        idx = args.index('--since')
        if idx + 1 < len(args):
            since_str = args[idx + 1]
            try:
                since = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
            except ValueError:
                print(f"Invalid timestamp: {since_str}")
                print("Use ISO format: 2026-03-15T10:00:00")
                return 1
    
    # Get tweets
    tweets_all, from_cache, meta = get_tweets(username, force=force)

    # "next" cursor is the newest tweet time we saw in the fetched feed (even if filtered out later)
    next_since = None
    if tweets_all:
        newest = max(t['pub_date'] for t in tweets_all if t.get('pub_date'))
        next_since = newest if newest.tzinfo else newest.replace(tzinfo=timezone.utc)

    tweets = tweets_all
    
    if not tweets:
        print(f"No tweets found for @{username}")
        if meta and meta.error_message:
            print(f"Error: {meta.error_message}")
        return 1
    
    # Filter if requested
    if since:
        tweets = filter_since(tweets, since)
    
    if no_rt:
        tweets = [t for t in tweets if not t['is_retweet']]
    
    if as_json:
        output = {
            'username': username,
            'tweets': [
                {
                    'id': t['id'],
                    'text': t['text'],
                    'author': t['author'],
                    'pub_date': t['pub_date'].isoformat(),
                    'url': t['url'],
                    'is_retweet': t['is_retweet'],
                    'is_reply': t['is_reply'],
                }
                for t in tweets
            ],
            'count': len(tweets),
            'from_cache': from_cache,
            'since': since.isoformat() if since else None,
            'next_since': next_since.isoformat() if next_since else None,
        }
        print(json.dumps(output))
        return 0
    
    # Human readable output
    source = "cache" if from_cache else "fresh"
    print(f"@{username} - {len(tweets)} tweets ({source})")
    if since:
        print(f"since: {since.isoformat()}")
    if next_since:
        print(f"next: --since {next_since.isoformat()}")
    print("")
    
    for t in tweets:
        prefix = "🔄 " if t['is_retweet'] else ("💬 " if t['is_reply'] else "")
        time_str = format_relative_time(t['pub_date'])
        print(f"{prefix}@{t['author']} · {time_str}")
        print(f"  {t['text']}")
        print(f"  {t['url']}\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
