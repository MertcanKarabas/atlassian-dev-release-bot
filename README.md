# atlassian-dev-release-bot

Daily Telegram digest of the [Atlassian developer changelog](https://developer.atlassian.com/changelog/),
with optional impact analysis against our own Bitbucket repositories.

## What it does

1. Reads the changelog RSS feed and keeps entries from the last 24 hours.
2. Marks entries as breaking based on their category (`Deprecation Notice`, `Removed`,
   `Changed`, `Security`, ...) or on wording like "will be removed" / "no longer".
3. For each breaking entry: extracts the identifiers it mentions (REST paths, package
   names, field names, scopes), `git grep`s them across our Bitbucket checkouts, and asks
   an LLM whether the evidence means our code is affected.
4. Sends one Telegram message: findings first, then the remaining updates.

Step 3 is optional. Without Bitbucket and LLM credentials the bot sends a plain digest.

## Setup

### Required — Telegram

| Secret | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | From `@BotFather` → `/mybots` → API Token |
| `TELEGRAM_CHAT_ID` | Your user id for a DM, or the group id (starts with `-`) |

Press **Start** in the bot's chat first, otherwise Telegram answers `chat not found`.
Find the id with `curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"`.

### Optional — Bitbucket impact analysis

| Secret | Value |
| --- | --- |
| `BITBUCKET_WORKSPACE` | Workspace slug, e.g. `mycompany` |
| `BITBUCKET_TOKEN` | Access token (repository, project or workspace) with `read:repository` |
| `BITBUCKET_EMAIL` | **Only** when `BITBUCKET_TOKEN` is an Atlassian *account* API token |

Two token flavours are supported:

- **Access token** (Repository/Project/Workspace settings → Access tokens) — leave
  `BITBUCKET_EMAIL` empty. Clones as `x-token-auth`, calls the API with `Bearer`.
- **Atlassian API token** (id.atlassian.com → API tokens, needs Bitbucket scopes) — set
  `BITBUCKET_EMAIL` to your Atlassian account email. Clones as `x-bitbucket-api-token-auth`.

Repos are shallow-cloned into `.repo-cache/` and cached between Actions runs.

### Optional — LLM

Any OpenAI-compatible chat endpoint works. Set `LLM_API_KEY` as a secret, and
`LLM_BASE_URL` / `LLM_MODEL` as repository variables.

| Provider | `LLM_BASE_URL` | `LLM_MODEL` | Cost |
| --- | --- | --- | --- |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | paid, very cheap (default) |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | free tier, rate-limited |
| OpenRouter | `https://openrouter.ai/api/v1` | any model ending in `:free` | free tier, rate-limited |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` | free tier |

Two requests per breaking entry, capped by `MAX_ANALYSED_ENTRIES` (default 10), so a
normal day costs ~10-20 short requests.

**Free tiers usually train on your data.** By default the model only receives changelog
text plus `repo/path:line` locations and matched identifiers — never source code. Set
`SEND_CODE_SNIPPETS=true` to also send the matching line, which improves accuracy at the
cost of sending code excerpts to the provider. Decide that against your own policy.

### Tuning

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOOKBACK_HOURS` | `24` | Feed window |
| `BITBUCKET_REPOS` | all | Comma-separated repo slugs to scan |
| `BITBUCKET_BRANCH` | default branch | Branch to scan in every repo |
| `MAX_REPOS` | `50` | Cap on repositories cloned |
| `MAX_ANALYSED_ENTRIES` | `10` | Cap on breaking entries sent to the LLM per run |
| `MAX_MATCHES_PER_TERM` | `15` | Cap on grep hits per search term |
| `SEND_CODE_SNIPPETS` | `false` | Include matched source lines in the LLM prompt |
| `CHANGELOG_RSS_URL` | all-products feed | Replace with a filtered feed from the changelog page's "Generate feed" dialog |

## Local run

```bash
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python bot.py
```

## Layout

| File | Role |
| --- | --- |
| `bot.py` | Orchestration and message rendering |
| `config.py` | Environment configuration |
| `changelog.py` | Feed fetching, parsing, breaking-change classification |
| `bitbucket.py` | Repository listing and shallow clone/refresh |
| `scanner.py` | Term extraction and `git grep` search |
| `llm.py` | OpenAI-compatible client, term refinement and impact verdicts |
| `notifier.py` | Telegram delivery and message chunking |
