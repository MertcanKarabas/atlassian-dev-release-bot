"""Thin client for any OpenAI-compatible chat API (DeepSeek, Groq, OpenRouter, ...)."""

import json
import re
import time

import requests

import config

JSON_BLOCK = re.compile(r"[\{\[].*[\}\]]", re.DOTALL)

TERMS_PROMPT = """You help a team find out whether an Atlassian platform change affects their code.

Given the changelog entry below, list the concrete strings a `grep` over a codebase
should look for: REST paths, package names, module keys, field names, scopes, class or
method names, config keys. Only strings that would literally appear in source code.
Never invent identifiers that are not implied by the entry. Prefer specific over generic;
skip anything shorter than 5 characters or as common as "api" or "cloud".

Return JSON only: {{"terms": ["...", "..."]}} with at most 10 entries.

TITLE: {title}
CATEGORY: {category}
BODY: {body}"""

SUMMARY_PROMPT = """You summarise Atlassian developer changelog entries for busy engineers.

For each entry write 2-4 sentences covering: what concretely changed, which product /
API / package it touches, why it matters, and any deadline or required migration. Name
specific identifiers (endpoints, fields, package names) when the entry gives them. Plain
facts, no preamble, no "this entry", no marketing words. Aim for 300-500 characters.

Return JSON only: {{"summaries": [{{"i": 0, "summary": "..."}}, ...]}}, one object per entry,
keeping the same "i" index you were given.

ENTRIES:
{entries}"""

ASSESS_PROMPT = """You assess whether an Atlassian platform change breaks a specific codebase.

CHANGELOG ENTRY
title: {title}
category: {category}
body: {body}

SEARCH RESULTS FROM THE TEAM'S BITBUCKET REPOSITORIES
repositories scanned: {repos}
search terms used: {terms}
matches:
{matches}

An empty match list means the searched identifiers appear nowhere in the code.
Judge only from this evidence. Do not assume usage that the matches do not show.

Return JSON only:
{{"impact": "AFFECTED" | "POSSIBLY_AFFECTED" | "NOT_AFFECTED",
  "confidence": 0.0-1.0,
  "reason": "at most 2 sentences, cite the matched identifier and repo",
  "action": "at most 1 sentence of concrete next step, or empty when not affected",
  "hotspots": ["repo/path:line", "..."]}}"""


class LLMError(RuntimeError):
    pass


def _chat(prompt):
    if not config.LLM_API_KEY:
        raise LLMError("LLM_API_KEY is not set.")

    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You answer with strict JSON and nothing else."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = ""
    for attempt in range(config.LLM_MAX_RETRIES):
        response = requests.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.LLM_TIMEOUT,
        )
        if response.ok:
            return response.json()["choices"][0]["message"]["content"]

        last_error = f"{response.status_code}: {response.text[:300]}"
        # Free tiers rate-limit aggressively; back off and retry those.
        if response.status_code in (408, 409, 429) or response.status_code >= 500:
            time.sleep(2 ** attempt * 3)
            continue
        if response.status_code == 400 and "response_format" in response.text:
            # Some gateways reject JSON mode; retry once without it.
            payload.pop("response_format", None)
            continue
        break

    raise LLMError(f"LLM request failed ({last_error})")


def _parse_json(text):
    try:
        return json.loads(text)
    except ValueError:
        pass
    block = JSON_BLOCK.search(text or "")
    if not block:
        raise LLMError(f"LLM returned no JSON: {text[:200]}")
    return json.loads(block.group(0))


def summarise_entries(entries):
    """One LLM call for all entries: return {uid: summary}. Empty dict on failure."""
    if not config.LLM_API_KEY or not entries:
        return {}

    rendered = "\n".join(
        f"[{i}] ({entry.category or 'update'}) {entry.title}\n"
        f"    {entry.text[:1400]}"
        for i, entry in enumerate(entries)
    )
    prompt = SUMMARY_PROMPT.format(entries=rendered)

    try:
        payload = _parse_json(_chat(prompt))
        rows = payload if isinstance(payload, list) else payload.get("summaries", [])
    except (LLMError, ValueError) as error:
        print(f"Summarisation failed, falling back to feed text: {error}")
        return {}

    summaries = {}
    for row in rows:
        try:
            index = int(row["i"])
            summary = str(row["summary"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if summary and 0 <= index < len(entries):
            summaries[entries[index].uid] = summary[:600]
    return summaries


def refine_terms(entry, seed_terms):
    """Ask the model for extra grep targets, merged with the regex-derived ones."""
    prompt = TERMS_PROMPT.format(
        title=entry.title,
        category=entry.category or "unspecified",
        body=entry.text[:4000],
    )
    try:
        extra = _parse_json(_chat(prompt)).get("terms", [])
    except (LLMError, ValueError) as error:
        print(f"Term refinement failed, using regex terms only: {error}")
        extra = []

    merged = list(seed_terms)
    seen = {term.lower() for term in merged}
    for term in extra:
        term = str(term).strip()
        if len(term) >= 5 and term.lower() not in seen:
            merged.append(term)
            seen.add(term.lower())
    return merged[:15]


def assess(entry, terms, matches, repo_names):
    """Ask the model whether the entry actually affects this codebase."""
    if config.SEND_CODE_SNIPPETS:
        rendered = "\n".join(f"- {m.location}  [{m.term}]  {m.line_text}" for m in matches)
    else:
        rendered = "\n".join(f"- {m.location}  [{m.term}]" for m in matches)

    prompt = ASSESS_PROMPT.format(
        title=entry.title,
        category=entry.category or "unspecified",
        body=entry.text[:4000],
        repos=", ".join(repo_names),
        terms=", ".join(terms) or "none",
        matches=rendered or "(no matches)",
    )
    verdict = _parse_json(_chat(prompt))
    impact = str(verdict.get("impact", "")).upper()
    if impact not in ("AFFECTED", "POSSIBLY_AFFECTED", "NOT_AFFECTED"):
        impact = "POSSIBLY_AFFECTED"
    verdict["impact"] = impact
    return verdict
