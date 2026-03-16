# Twitter RSS Options - Research & Comparison

Research conducted: 2026-03-15

## Goal
Find a free, CLI-friendly way to consume Twitter/X feeds for single-account monitoring with local caching and minimal fetches.

---

## Options Evaluated

### 1. xcancel.com

**What it is:** A Nitter fork/instance that proxies Twitter content.

**How it works:**
- Scrapes Twitter and serves it as lightweight HTML + RSS
- Uses sophisticated request fingerprinting to identify clients
- Generates unique fingerprint hash per request (changes every time)
- Blocks unknown clients with "RSS reader not yet whitelisted!" message

**Fingerprinting method:**
- NOT just User-Agent (tested NetNewsWire, Feedly, Inoreader - all blocked)
- Likely includes: TLS handshake (JA3), IP, header ordering, connection behavior
- Each request gets unique ID requiring email to rss@xcancel.com for whitelisting

**Verdict:** ❌ Not suitable for CLI/automated access without manual whitelisting process.

---

### 2. nitter.net (Official Instance)

**What it is:** The official Nitter instance run by project maintainer (zedeus).

**How it works:**
- Nim-based proxy that scrapes Twitter's unofficial API
- Serves lightweight HTML interface + RSS feeds
- Runs on dedicated infrastructure
- Requires browser-like User-Agent (RSS reader UAs get blocked)

**RSS Endpoint:**
```
https://nitter.net/{username}/rss
```

**Rate limiting / TTL:**
- RSS feed includes `<ttl>40</ttl>` (40 minutes)
- Suggests refreshing no more frequently than every 40 minutes
- Single-user human-scale consumption = fine
- Heavy scraping will get blocked

**Usage policy:**
- Intended for personal use
- Status monitoring: https://status.d420.de/
- Status page explicitly asks: "Please do NOT use these instances for scraping!"

**Verdict:** ✅ **Selected option** - works reliably, reasonable rate limits, minimal resource usage on our end.

---

### RSS Feed Details (What You Actually Get)

After testing the actual feed output, here's what the nitter.net RSS endpoint returns:

**Feed Structure:**
```xml
<rss version="2.0">
  <channel>
    <title>Elon Musk / @elonmusk</title>
    <ttl>40</ttl>                    <!-- Suggested refresh interval (minutes) -->
    <item>...</item>                 <!-- Tweet 1 -->
    <item>...</item>                 <!-- Tweet 2 -->
    ...
  </channel>
</rss>
```

**Item Count:** Exactly **20 items** per request
- This is hardcoded in Nitter's source (`src/api.nim`): `"count": 20`
- NOT configurable via URL parameters
- Issue #228 on GitHub asked about this - no URL parameter exists

**What Counts Toward the 20:**
| Content Type | Counted? | Notes |
|--------------|----------|-------|
| Original tweets | ✅ Yes | Your own tweets |
| Retweets | ✅ Yes | Shown as "RT by @user: ..." |
| Replies | ✅ Yes | Shown as "R to @user: ..." |
| Quote tweets | ✅ Yes | Embedded in description |
| Pinned tweets | ✅ Yes | Inserted at top if present |

**Time Range:** Variable (depends on posting frequency)
- For active accounts: ~6-12 hours of history
- For less active accounts: days or weeks
- Example: @elonmusk's 20 items span ~7 hours on a busy day

**Available RSS Endpoints:**
```
/{username}/rss              # Tweets only (default)
/{username}/with_replies/rss # Include replies
/{username}/media/rss        # Media only
/i/lists/{id}/rss            # List feeds
/search/rss?q={query}        # Search results (if enabled)
```

**Customization Options:** ❌ None at request time
- No `?limit=` or `?count=` parameter
- No `?since=` or date range filtering
- No exclusion filters (can't skip RTs, etc)

**Pagination:** Via cursor (Min-Id header)
- Response includes `Min-Id` HTTP header with snowflake ID
- Next page: `/{username}/rss?cursor={min_id}`
- But this is per-request pagination, not RSS-standard

---

### 3. Other Nitter Instances

Per https://status.d420.de/ (instance health tracker):

| Instance | RSS Working | Notes |
|----------|-------------|-------|
| nitter.net | ✅ | Official, best uptime |
| nitter.poast.org | ✅ | Sometimes down |
| nitter.catsarch.com | ❌ | No RSS |
| nitter.tiekoetter.com | ❌ | No RSS |
| xcancel.com | ✅ | Requires whitelisting |
| farside.link/nitter | ❌ | 403/redirect issues |

Most instances have disabled RSS or are unreliable. nitter.net is the most stable option.

---

## How nitter.net Works (Technical)

### Architecture
```
Your Client → nitter.net → Twitter/X API (via real accounts)
                ↓
            Redis cache
                ↓
           RSS/HTML response
```

### Backend Details
- **Language:** Nim (compiles to native binary)
- **Cache:** Redis/Valkey for storing tweets, profiles, timelines
- **Auth:** Uses real Twitter/X account session tokens (since Jan 2024)
- **RSS Generation:** Dynamic from cached data

### Request Flow
1. Your request hits nitter.net
2. Check Redis cache first
3. If miss: use session token to call Twitter's internal API
4. Parse response, store in Redis
5. Generate RSS XML from cached data

---

## Self-Hosting Nitter (Future Option)

### Why Consider It
- No dependency on public instances
- Can customize rate limits
- Full control over data
- Can monitor many accounts without hitting shared limits

### Requirements

| Resource | Spec |
|----------|------|
| RAM | ~300-500 MB (nitter + Redis) |
| CPU | Minimal (2 cores sufficient) |
| Storage | ~100 MB + cache growth |
| Network | Moderate (scales with usage) |

**Pi 5 Suitability:** ✅ Excellent fit

### Components Needed
1. **Nitter binary** (Nim-compiled static executable)
2. **Redis/Valkey** (caching)
3. **Twitter/X account(s)** with valid session tokens

### The Account Token Hassle (Key Complexity)

Since Jan 2024, Twitter killed guest API access:

```
Before 2024: Nitter worked without accounts (guest tokens)
After 2024:  Requires real X accounts for API access
```

**Process:**
1. Create throwaway X account
2. Run Python script to extract session tokens (auth_token, ct0)
3. Store in `sessions.jsonl` file
4. Tokens can expire or account can get rate-limited/banned
5. Must regenerate tokens when this happens

**Scripts provided:**
- `create_session_browser.py` — browser automation (slower, more reliable)
- `create_session_curl.py` — HTTP requests (faster, may trigger bot detection)

### Maintenance Burden

| Aspect | Frequency | Effort |
|--------|-----------|--------|
| Token refresh | Variable (weeks-months) | Medium |
| Updates when Twitter breaks API | Regular | Low-Medium |
| Nitter version updates | As needed | Low |

**Reality:** Not "set and forget" — requires babysitting when Twitter changes things.

### Docker Setup (Quick Reference)

```yaml
version: "3"
services:
  nitter:
    image: zedeus/nitter:latest-arm64  # For Pi 5
    ports:
      - "8080:8080"
    volumes:
      - ./nitter.conf:/src/nitter.conf:ro
      - ./sessions.jsonl:/src/sessions.jsonl:ro
    depends_on:
      - redis
  redis:
    image: redis:6-alpine
    volumes:
      - redis-data:/data
volumes:
  redis-data:
```

### When Self-Hosting Makes Sense

✅ **Do it if:**
- You want to monitor many accounts heavily
- You don't want dependency on public instances
- You're comfortable with X account token maintenance
- You want to experiment with the project

❌ **Skip if:**
- Single-user RSS monitoring is all you need
- You want minimal maintenance
- You don't have spare X accounts to risk

---

## Our Solution: Cached Fetcher with TTL Management

**Approach:** Use nitter.net with sophisticated local caching to minimize fetches and respect rate limits.

### Architecture

```
cli.py (UI/commands) → nitter_client.py (TTL logic) → nitter.net
                              ↓
                        storage.py (per-account dated directories)
```

**Key design:** `nitter_client.py` is the ONLY module making HTTP requests. All consuming code goes through it to ensure TTL and rate limits are respected.

### TTL Policy

| Response Type | TTL | Rationale |
|---------------|-----|-----------|
| Success (200) | 120 min | Respect nitter.net's 40-min hint + buffer |
| Network error | 1 min | Retry quickly for transient issues |
| Rate limited (429) | 5 min | Back off when server asks |
| Server error (5xx) | 2 min | Temporary server issues |
| Client error (4xx) | 10 min | Likely config issue, don't hammer |
| Parse error | 1 min | Might be temporary malformed response |

### Data Structure

```
data/accounts/
└── {username}/
    ├── 20260315-184522/        # Timestamped directory
    │   ├── feed.xml            # Raw RSS
    │   └── meta.json           # TTL, status, timestamps
    └── latest.json             # Pointer to most recent
```

### Features

- **Cache validation:** Checks expiry before every request
- **Error handling:** Different retry strategies per error type
- **Only success cached:** Errors don't pollute cache
- **History preserved:** Multiple dated directories per account
- **CLI tools:** `fetch`, `status`, `history`, `export`, `clean`

### Usage

```bash
python cli.py fetch elonmusk          # Fetch with cache
python cli.py fetch elonmusk --force  # Bypass cache
python cli.py status                  # Check all accounts
python cli.py history elonmusk        # View fetch history
python cli.py export elonmusk         # Export as JSON
```

---

## Files in This Project

| File | Purpose |
|------|---------|
| `nitter_client.py` | **Core client** - HTTP requests, TTL logic, error handling |
| `storage.py` | Per-account file organization, metadata management |
| `config.py` | TTL settings, paths, constants |
| `cli.py` | User interface, commands |
| `RESEARCH.md` | This document |
| `README.md` | Quick usage guide |
| `data/accounts/` | Cached feeds (gitignored) |

---

## Resources

- Nitter GitHub: https://github.com/zedeus/nitter
- Instance Status: https://status.d420.de/
- Session Token Guide: https://github.com/zedeus/nitter/wiki/Creating-session-tokens
- Instance List: https://github.com/zedeus/nitter/wiki/Instances
