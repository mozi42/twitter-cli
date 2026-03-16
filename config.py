"""
Configuration for Twitter RSS fetcher.

Cache paths use XDG (~/.cache) by default,
allowing the CLI to work from any working directory and survive repo moves.
Override with TWITTER_CLI_DATA_DIR.
"""

from pathlib import Path
import os

# Resolve through symlinks for robustness when invoked via ~/.local/bin/twitter-cli
PROJECT_DIR = Path(__file__).resolve().parent

# Nitter instance to use
NITTER_HOST = "nitter.net"

# Request settings
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

# TTL settings (in seconds)
class TTL:
    SUCCESS = 120 * 60        # 2 hours for successful responses
    NETWORK_ERROR = 60        # 1 minute for network issues
    RATE_LIMITED = 5 * 60     # 5 minutes when rate limited
    SERVER_ERROR = 2 * 60     # 2 minutes for server errors
    CLIENT_ERROR = 10 * 60    # 10 minutes for client errors (likely config issue)
    PARSE_ERROR = 60          # 1 minute for parse errors (might be temporary)
    
    @classmethod
    def get_for_status(cls, http_status: int | None, parse_error: bool = False) -> int:
        """Get TTL based on HTTP status and error type."""
        if parse_error:
            return cls.PARSE_ERROR
        if http_status is None:
            return cls.NETWORK_ERROR
        if http_status == 429:
            return cls.RATE_LIMITED
        if 500 <= http_status < 600:
            return cls.SERVER_ERROR
        if 400 <= http_status < 500:
            return cls.CLIENT_ERROR
        if 200 <= http_status < 300:
            return cls.SUCCESS
        return cls.NETWORK_ERROR

# Paths
# Use XDG cache dir so the CLI works from any CWD and survives repo moves.
# Can be overridden with TWITTER_CLI_DATA_DIR.
_DEFAULT_CACHE_ROOT = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
DATA_DIR = Path(os.environ.get("TWITTER_CLI_DATA_DIR", _DEFAULT_CACHE_ROOT / "twitter-cli"))
ACCOUNTS_DIR = DATA_DIR / "accounts"

# Ensure directories exist
def ensure_dirs():
    """Create necessary directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
