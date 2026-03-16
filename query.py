"""
Stateless Twitter feed query interface.

Provides timestamp-based filtering to get only new/missed tweets.
The query is stateless - it returns tweets and tells you what timestamp
to use for the next query, but doesn't track state itself.

Usage:
    result = query_tweets("elonmusk", since=datetime(2026, 3, 15, 10, 0))
    for tweet in result.tweets:
        print(tweet.text)
    
    # For next query, use result.next_since
    next_result = query_tweets("elonmusk", since=result.next_since)

If since is None, returns the 20 newest tweets.
"""

from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass

from nitter_client import NitterClient, get_feed
from storage import StorageManager


@dataclass
class Tweet:
    """Structured tweet data from RSS."""
    id: str
    text: str
    author: str
    author_display: str
    pub_date: datetime
    url: str
    is_retweet: bool
    is_reply: bool
    is_pinned: bool
    media_urls: List[str]
    quoted_tweet: Optional['Tweet']  # For quote tweets


@dataclass
class QueryResult:
    """Result of a query operation."""
    username: str
    tweets: List[Tweet]
    fetched_at: datetime
    since: Optional[datetime]  # What was passed in
    next_since: datetime  # Timestamp of newest tweet (use this next time)
    came_from_cache: bool
    count_returned: int
    count_available: int  # Total in feed (always 20 unless error)


def _parse_rfc822(date_str: str) -> Optional[datetime]:
    """Parse RFC 822 date format used in RSS."""
    if not date_str:
        return None
    
    # feedparser returns a time.struct_time, but we may get raw strings
    # Try common formats
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


def _parse_entry(entry) -> Tweet:
    """Convert a feedparser entry to a Tweet dataclass."""
    title = getattr(entry, 'title', '')
    
    # Determine tweet type from title prefix
    is_retweet = title.startswith("RT by ")
    is_reply = title.startswith("R to ")
    is_pinned = title.startswith("Pinned: ")
    
    # Get author from dc:creator or parse from title
    author = getattr(entry, 'dc_creator', '')
    if not author and is_retweet:
        # For retweets, author is in the RT attribution
        # Extract from title: "RT by @user: actual tweet"
        author = title.split(":")[0].replace("RT by ", "")
    
    # Get pub date
    pub_date = None
    if hasattr(entry, 'published'):
        pub_date = _parse_rfc822(entry.published)
    if not pub_date and hasattr(entry, 'updated'):
        pub_date = _parse_rfc822(entry.updated)
    if not pub_date:
        pub_date = datetime.now(timezone.utc)  # Fallback
    
    # Make timezone-aware
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=timezone.utc)
    
    return Tweet(
        id=getattr(entry, 'guid', getattr(entry, 'id', '')),
        text=getattr(entry, 'description', ''),
        author=author.lstrip('@') if author else '',
        author_display=author,
        pub_date=pub_date,
        url=getattr(entry, 'link', ''),
        is_retweet=is_retweet,
        is_reply=is_reply,
        is_pinned=is_pinned,
        media_urls=[],  # Extract from description if needed
        quoted_tweet=None,
    )


def query_tweets(
    username: str,
    since: Optional[datetime] = None,
    force_refresh: bool = False,
    include_retweets: bool = True,
    include_replies: bool = False,
) -> QueryResult:
    """
    Query tweets for a user, optionally filtering to those newer than 'since'.
    
    This function is STATELESS - it doesn't track what you've seen. You pass
    in a timestamp, it returns tweets after that timestamp, and tells you
    what timestamp to use next time.
    
    Args:
        username: Twitter handle (without @)
        since: Optional datetime - only return tweets newer than this.
               If None, returns all 20 newest tweets.
        force_refresh: Bypass cache and fetch fresh from nitter.net
        include_retweets: If False, filter out retweets
        include_replies: If False, filter out replies (default True for RSS)
    
    Returns:
        QueryResult with tweets (newest first) and metadata for next query
    
    Example:
        # First query - get latest
        result = query_tweets("elonmusk")
        print(f"Got {len(result.tweets)} tweets")
        
        # Store result.next_since somewhere
        last_seen = result.next_since
        
        # Later...
        result = query_tweets("elonmusk", since=last_seen)
        # Only returns tweets newer than last_seen
    """
    username = username.lower().strip()
    
    # Get feed (uses cache if valid)
    fetch_result = get_feed(username, force=force_refresh)
    
    if not fetch_result.success:
        # Return empty result on error
        return QueryResult(
            username=username,
            tweets=[],
            fetched_at=datetime.now(timezone.utc),
            since=since,
            next_since=since or datetime.now(timezone.utc),
            came_from_cache=fetch_result.came_from_cache,
            count_returned=0,
            count_available=0,
        )
    
    # Parse all entries
    entries = fetch_result.parsed_feed.entries if fetch_result.parsed_feed else []
    all_tweets = [_parse_entry(e) for e in entries]
    
    # Filter by timestamp if since provided
    if since:
        # Make since timezone-aware if needed
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        
        # Only tweets AFTER since (strictly greater, not equal)
        tweets = [t for t in all_tweets if t.pub_date > since]
    else:
        tweets = all_tweets
    
    # Apply content filters
    if not include_retweets:
        tweets = [t for t in tweets if not t.is_retweet]
    
    if not include_replies:
        tweets = [t for t in tweets if not t.is_reply]
    
    # Determine next_since - timestamp of newest returned tweet
    # If no tweets returned, use the input since (or now if no input)
    if tweets:
        next_since = tweets[0].pub_date  # Newest first
    elif all_tweets:
        # No new tweets, but we have data - use newest in feed
        next_since = all_tweets[0].pub_date
    else:
        next_since = since or datetime.now(timezone.utc)
    
    return QueryResult(
        username=username,
        tweets=tweets,
        fetched_at=datetime.now(timezone.utc),
        since=since,
        next_since=next_since,
        came_from_cache=fetch_result.came_from_cache,
        count_returned=len(tweets),
        count_available=len(all_tweets),
    )


def get_cache_timestamp(username: str) -> Optional[datetime]:
    """
    Get the timestamp of the newest tweet in cache.
    Useful for determining where to start from.
    
    Returns None if no cache exists.
    """
    username = username.lower().strip()
    storage = StorageManager.get_account(username)
    cached = storage.get_latest()
    
    if not cached:
        return None
    
    # Parse the cached feed to get newest tweet date
    feed_path, meta = cached
    try:
        import feedparser
        feed_data = feed_path.read_bytes()
        parsed = feedparser.parse(feed_data)
        
        if parsed.entries:
            newest = _parse_entry(parsed.entries[0])
            return newest.pub_date
    except Exception:
        pass
    
    return None


# Convenience function for simple "what's new" queries
def whats_new(username: str, since: datetime) -> List[Tweet]:
    """
    Simple convenience: get only new tweets since a timestamp.
    
    Args:
        username: Twitter handle
        since: datetime to check from
    
    Returns:
        List of new tweets (empty if none or error)
    """
    result = query_tweets(username, since=since)
    return result.tweets


if __name__ == "__main__":
    # CLI testing
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python query.py <username> [--since ISO_TIMESTAMP] [--no-rt]")
        sys.exit(1)
    
    username = sys.argv[1]
    since = None
    include_rt = True
    
    for i, arg in enumerate(sys.argv):
        if arg == "--since" and i + 1 < len(sys.argv):
            since_str = sys.argv[i + 1]
            try:
                since = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
            except ValueError:
                print(f"Invalid timestamp: {since_str}")
                sys.exit(1)
        if arg == "--no-rt":
            include_rt = False
    
    result = query_tweets(username, since=since, include_retweets=include_rt)
    
    print(f"\n{'='*60}")
    print(f"Query: @{result.username}")
    print(f"Since: {result.since or 'None (latest 20)'}")
    print(f"Fetched at: {result.fetched_at}")
    print(f"From cache: {result.came_from_cache}")
    print(f"Returned: {result.count_returned} of {result.count_available} available")
    print(f"Next since: {result.next_since.isoformat()}")
    print(f"{'='*60}")
    
    for tweet in result.tweets:
        prefix = ""
        if tweet.is_retweet:
            prefix = "[RT] "
        elif tweet.is_reply:
            prefix = "[Reply] "
        elif tweet.is_pinned:
            prefix = "[Pinned] "
        
        print(f"\n{prefix}{tweet.author} @ {tweet.pub_date.isoformat()}")
        # Truncate text for display
        text = tweet.text[:200].replace('\n', ' ')
        if len(tweet.text) > 200:
            text += "..."
        print(f"  {text}")
    
    # Output next_since as JSON for piping
    print(f"\n{{\"next_since\": \"{result.next_since.isoformat()}\"}}")
