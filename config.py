"""Central configuration, read once from the environment."""

import os


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def _env_int(name, default):
    raw = _env(name)
    return int(raw) if raw else default


def _env_bool(name, default=False):
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_list(name):
    return [item.strip() for item in _env(name).split(",") if item.strip()]


# --- Changelog feed ---------------------------------------------------------
# The changelog landing page is a JavaScript app, not a feed. This is the real
# RSS endpoint, generated from the changelog page's "Generate feed" dialog with
# no filters applied (all types, all components).
RSS_URL = _env(
    "CHANGELOG_RSS_URL",
    "https://developer.atlassian.com/changelog/rss/a/f859a215-65f3-4ebc-b7dd-10007cfd7f60",
)
LOOKBACK_HOURS = _env_int("LOOKBACK_HOURS", 24)

# --- Telegram ---------------------------------------------------------------
BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
CHAT_ID = _env("TELEGRAM_CHAT_ID")
TELEGRAM_MAX_CHARS = 4096

# --- Bitbucket --------------------------------------------------------------
BITBUCKET_WORKSPACE = _env("BITBUCKET_WORKSPACE")
BITBUCKET_TOKEN = _env("BITBUCKET_TOKEN")
# Set BITBUCKET_EMAIL only when BITBUCKET_TOKEN is an Atlassian account API token.
# Leave it empty for repository/project/workspace access tokens.
BITBUCKET_EMAIL = _env("BITBUCKET_EMAIL")
# Explicit repo slugs; empty means "every repo in the workspace".
BITBUCKET_REPOS = _env_list("BITBUCKET_REPOS")
# Branch to scan. Empty means each repo's default branch.
BITBUCKET_BRANCH = _env("BITBUCKET_BRANCH")
MAX_REPOS = _env_int("MAX_REPOS", 50)
CLONE_DIR = _env("CLONE_DIR", ".repo-cache")

# --- LLM (any OpenAI-compatible endpoint) -----------------------------------
LLM_API_KEY = _env("LLM_API_KEY")
LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
LLM_MODEL = _env("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = _env_int("LLM_TIMEOUT", 120)
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 4)

# --- Analysis behaviour -----------------------------------------------------
# One-line summary under every entry. Uses the LLM in a single batched call when
# LLM_API_KEY is set, otherwise falls back to trimmed feed text. Set false for titles only.
SUMMARISE_ENTRIES = _env_bool("SUMMARISE_ENTRIES", True)
# Cap the number of changelog entries sent through the LLM in one run.
MAX_ANALYSED_ENTRIES = _env_int("MAX_ANALYSED_ENTRIES", 10)
MAX_MATCHES_PER_TERM = _env_int("MAX_MATCHES_PER_TERM", 15)
MAX_MATCHES_PER_ENTRY = _env_int("MAX_MATCHES_PER_ENTRY", 60)
# When false, the LLM sees repo/file/line locations but never the source line
# itself. Turn on only if you accept sending code excerpts to your LLM provider.
SEND_CODE_SNIPPETS = _env_bool("SEND_CODE_SNIPPETS", False)

ANALYSIS_ENABLED = bool(BITBUCKET_WORKSPACE and BITBUCKET_TOKEN and LLM_API_KEY)
