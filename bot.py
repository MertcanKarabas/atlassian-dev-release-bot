"""Daily Atlassian developer changelog digest, with impact analysis on our Bitbucket code.

Without Bitbucket/LLM credentials the bot sends a plain digest of the last 24 hours.
With them configured, every entry is grepped against the team's repositories and an LLM
judges whether the change touches our code, so each update carries its own verdict.
"""

import html
import sys

import bitbucket
import changelog
import config
import llm
import notifier
import scanner

# Prefix shown before every entry: impact colour + one-word verdict.
IMPACT_PREFIX = {
    "AFFECTED": "🔴",
    "POSSIBLY_AFFECTED": "🟠",
    "NOT_AFFECTED": "🟢",
    "UNKNOWN": "⚪",
}
IMPACT_VERDICT = {
    "AFFECTED": "⚠️ May affect your code",
    "POSSIBLY_AFFECTED": "❓ Might affect your code — worth a look",
    "NOT_AFFECTED": "✅ Does not affect your code",
    "UNKNOWN": "▫️ Not scanned",
}
IMPACT_ORDER = ("AFFECTED", "POSSIBLY_AFFECTED", "NOT_AFFECTED", "UNKNOWN")


def _link(entry):
    title = html.escape(entry.title)
    link = html.escape(entry.link, quote=True)
    return f"<a href=\"{link}\">{title}</a>"


def _category(entry):
    """Short, human bracket label, e.g. [Deprecation] or [Added]."""
    label = (entry.category or "Update").replace("Notice", "").strip()
    label = label.replace("Request for Comments (RFC)", "RFC")
    return f"[{html.escape(label)}]"


def analyse(entries, repos):
    """Return {uid: verdict} for every entry (capped), grepping our repos for evidence."""
    repo_names = [repo.slug for repo in repos]

    # Breaking entries first so the cap never drops the ones that matter most.
    ordered = sorted(entries, key=lambda entry: not entry.is_breaking)
    scanned = ordered[: config.MAX_ANALYSED_ENTRIES]
    if len(ordered) > len(scanned):
        print(
            f"Scanning {len(scanned)} of {len(ordered)} entries "
            "(raise MAX_ANALYSED_ENTRIES to cover all)."
        )

    verdicts = {}
    for entry in scanned:
        seed = scanner.candidate_terms(entry)
        # Only spend an LLM call refining terms when there is something to refine.
        terms = llm.refine_terms(entry, seed) if (seed or entry.is_breaking) else seed

        if not terms:
            verdicts[entry.uid] = {
                "impact": "NOT_AFFECTED",
                "reason": "This update references no API or code identifiers to check.",
                "action": "",
                "hotspots": [],
            }
            print(f"{entry.title[:55]!r}: no terms -> NOT_AFFECTED")
            continue

        matches = scanner.search(repos, terms)
        print(f"{entry.title[:55]!r}: {len(terms)} terms, {len(matches)} matches")

        if not matches:
            shown = ", ".join(terms[:6])
            verdicts[entry.uid] = {
                "impact": "NOT_AFFECTED",
                "reason": f"Searched your {len(repo_names)} repositories for {shown}; "
                "none of these appear in the code.",
                "action": "",
                "hotspots": [],
            }
            continue

        try:
            verdicts[entry.uid] = llm.assess(entry, terms, matches, repo_names)
        except (llm.LLMError, ValueError) as error:
            print(f"Assessment failed for {entry.uid}: {error}", file=sys.stderr)
            verdicts[entry.uid] = {
                "impact": "POSSIBLY_AFFECTED",
                "reason": "Matches found but automatic assessment failed; review manually.",
                "action": "",
                "hotspots": sorted({m.location for m in matches})[:5],
            }
    return verdicts


def build_summaries(entries):
    """Return {uid: one-line summary}, LLM-batched when possible, feed-text otherwise."""
    if not config.SUMMARISE_ENTRIES:
        return {}
    summaries = llm.summarise_entries(entries) if config.LLM_API_KEY else {}
    # Fill any gaps (LLM off, failed, or skipped an entry) with trimmed feed prose.
    for entry in entries:
        if not summaries.get(entry.uid):
            fallback = changelog.short_summary(entry.text)
            if fallback:
                summaries[entry.uid] = fallback
    return summaries


def _entry_block(entry, verdict, summary):
    """One entry: category + title, detailed summary, impact verdict, action, hotspots."""
    impact = (verdict or {}).get("impact", "UNKNOWN")
    prefix = IMPACT_PREFIX.get(impact, "⚪")

    lines = [f"{prefix} {_category(entry)} {_link(entry)}"]
    if summary:
        lines.append(f"  {html.escape(summary)}")

    if verdict:
        lines.append(f"  {IMPACT_VERDICT.get(impact, impact)}")
        reason = str(verdict.get("reason", "")).strip()
        if reason:
            lines.append(f"  <i>{html.escape(reason)}</i>")
        action = str(verdict.get("action", "")).strip()
        if action and impact != "NOT_AFFECTED":
            lines.append(f"  ➡️ {html.escape(action)}")
        hotspots = [str(spot) for spot in verdict.get("hotspots", [])][:5]
        if hotspots:
            lines.append("  📍 " + html.escape(", ".join(hotspots)))

    return "\n".join(lines)


def render_blocks(entries, verdicts, summaries):
    """Build the Telegram message body; when analysed, most-affected entries first."""
    if verdicts:
        ordered = sorted(
            entries,
            key=lambda entry: (
                IMPACT_ORDER.index(verdicts.get(entry.uid, {}).get("impact", "UNKNOWN")),
                -entry.published.timestamp(),
            ),
        )
    else:
        ordered = entries  # feed order (newest first) for plain digest mode

    return [
        _entry_block(entry, verdicts.get(entry.uid), summaries.get(entry.uid))
        for entry in ordered
    ]


def main():
    if not config.BOT_TOKEN or not config.CHAT_ID:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set.")

    entries = changelog.fetch_recent_entries()
    if not entries:
        notifier.send(
            "<b>🚀 Atlassian Developer Updates</b>\n\n"
            f"No new release notes in the {config.WINDOW_LABEL.lower()}. 💤"
        )
        return

    verdicts = {}
    if config.ANALYSIS_ENABLED:
        try:
            verdicts = analyse(entries, bitbucket.sync_repositories())
        except RuntimeError as error:
            print(f"Impact analysis unavailable: {error}", file=sys.stderr)
            verdicts = {}
    else:
        print(
            "Impact analysis disabled "
            "(needs BITBUCKET_WORKSPACE, BITBUCKET_TOKEN and LLM_API_KEY)."
        )

    summaries = build_summaries(entries)

    header_lines = [f"<b>🚀 Atlassian Developer Updates ({config.WINDOW_LABEL})</b>"]
    if verdicts:
        hits = sum(
            1 for v in verdicts.values() if v.get("impact") in ("AFFECTED", "POSSIBLY_AFFECTED")
        )
        header_lines.append(
            f"🔎 {len(entries)} updates · "
            + (f"⚠️ {hits} may touch your code" if hits else "✅ none touch your code")
        )
    header = "\n".join(header_lines)

    blocks = render_blocks(entries, verdicts, summaries)
    for message in notifier.split_messages(blocks, header):
        notifier.send(message)


if __name__ == "__main__":
    main()
