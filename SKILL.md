---
name: twitter-cli
description: Fetches tweets for a specific user via Nitter RSS and prints a compact timeline with since/next cursor hints. Uses HTTP requests to Nitter instances plus a local XDG cache with TTL backoff. Use when monitoring a specific account for new posts since a given time.
version: 1
tags: [cli, rss, twitter]
metadata:
  git_remote: ""
  managed_by: mozi
---

## What this skill is

A small CLI that fetches tweets for a single user via **Nitter RSS**, then prints a compact timeline.

It’s meant for “check this account every so often; only care about what’s new since last time” workflows.

## Files

- `twitter-cli.py` — entrypoint (the `twitter-cli` command)
- `nitter_client.py` — fetch logic + instance selection + TTL/backoff
- `query.py` — RSS parsing + tweet extraction
- `storage.py` — filesystem cache (success + error backoff)

## Install

```bash
bash skills/twitter-cli/install.sh
```

Creates/updates a symlink:
- `~/.local/bin/twitter-cli` → `<workspace>/skills/twitter-cli/twitter-cli.py`

## Usage

```bash
twitter-cli openai
twitter-cli openai --since 2026-03-15T10:00:00+00:00
twitter-cli openai --force
```

### Caching

- Default cache: `~/.cache/twitter-cli/accounts/<username>/...`
- Override: set `TWITTER_CLI_DATA_DIR=/some/path`
- The cache stores **successful fetches** and also caches **errors** (e.g. 404/timeout) for a short TTL so repeated calls don’t hammer Nitter.

### Output conventions (text mode)

- If `--since` is provided, output includes `since: <iso>`.
- Output includes `next: --since <iso>` based on the newest tweet timestamp seen in the fetched feed.
