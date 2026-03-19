# twitter-cli

Simple CLI for fetching Twitter/X feeds via Nitter RSS. Gets tweets, caches them, minimal fuss. No API key required.

## Install

```bash
# Dependencies
sudo apt install python3-feedparser python3-requests

# Install CLI (symlinks to ~/.local/bin/)
./install.sh
```

## Usage

```bash
# Get tweets (uses cache if valid, else fetches)
twitter-cli elonmusk

# Force fresh fetch
twitter-cli elonmusk --force

# JSON output
twitter-cli elonmusk --json

# Exclude retweets
twitter-cli elonmusk --no-rt

# Only tweets after specific time
twitter-cli elonmusk --since 2026-03-15T10:00:00
```

That's it. Cache is automatic (2 hour TTL), stored in `~/.cache/twitter-cli/accounts/` (XDG).
Override with `TWITTER_CLI_DATA_DIR` if needed.

## How It Works

- **Default**: Returns last 20 tweets from cache if valid, otherwise fetches fresh
- **--force**: Ignores cache, always fetches fresh
- **--since**: Filters to tweets after timestamp (for "what's new" use cases)
- **--no-rt**: Filters out retweets
- **--json**: Machine-readable output

## Cache

Default location (XDG):
- `~/.cache/twitter-cli/accounts/<username>/`

Layout:
- `<timestamp>/feed.xml` (only on success)
- `<timestamp>/meta.json` (success or error)
- `latest.json` (pointer to most recent attempt)

TTL: 2 hours for successful responses by default. Errors are also cached briefly (backoff) so repeated calls don’t hammer Nitter.
Override base dir with `TWITTER_CLI_DATA_DIR`.

## Files

| File | Purpose |
|------|---------|
| `twitter-cli.py` | CLI - just get tweets |
| `nitter_client.py` | HTTP client with TTL logic |
| `storage.py` | File organization |
| `config.py` | Paths, TTL settings |
| `query.py` | Timestamp filtering (used internally) |
