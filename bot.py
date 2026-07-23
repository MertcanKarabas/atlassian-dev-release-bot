"""Daily Atlassian developer changelog digest, with impact analysis on our Bitbucket code.

Without Bitbucket/LLM credentials the bot behaves as before: a plain digest of the
last 24 hours. With them configured, every breaking entry is grepped against the
team's repositories and an LLM judges whether the change touches our code.
"""

import html
import sys

import bitbucket
import changelog
import config
import llm
import notifier
import scanner

IMPACT_BADGE = {
    "AFFECTED": "🔴 AFFECTED",
    "POSSIBLY_AFFECTED": "🟠 POSSIBLY AFFECTED",
    "NOT_AFFECTED": "🟢 not affected",
}


def _link(entry):
    title = html.escape(entry.title)
    link = html.escape(entry.link, quote=True)
    return f"<a href=\"{link}\">{title}</a>"


def analyse(entries, repos):
    """Return [(entry, verdict)] for entries that look breaking."""
    repo_names = [repo.slug for repo in repos]
    breaking = [entry for entry in entries if entry.is_breaking]
    if len(breaking) > config.MAX_ANALYSED_ENTRIES:
        print(
            f"Analysing the first {config.MAX_ANALYSED_ENTRIES} of {len(breaking)} "
            "breaking entries (raise MAX_ANALYSED_ENTRIES to cover all)."
        )
        breaking = breaking[: config.MAX_ANALYSED_ENTRIES]

    results = []
    for entry in breaking:
        terms = llm.refine_terms(entry, scanner.candidate_terms(entry))
        matches = scanner.search(repos, terms)
        print(f"{entry.title[:60]!r}: {len(terms)} terms, {len(matches)} matches")
        try:
            verdict = llm.assess(entry, terms, matches, repo_names)
        except (llm.LLMError, ValueError) as error:
            print(f"Assessment failed for {entry.uid}: {error}", file=sys.stderr)
            verdict = {
                "impact": "POSSIBLY_AFFECTED",
                "reason": "Automatic assessment failed; review manually.",
                "action": "",
                "hotspots": [location for location in {m.location for m in matches}][:5],
            }
        results.append((entry, verdict))
    return results


def render_blocks(entries, analysis):
    """Build the Telegram message body, impact findings first."""
    blocks = []
    assessed = {entry.uid for entry, _ in analysis}

    for entry, verdict in sorted(
        analysis,
        key=lambda item: ("AFFECTED", "POSSIBLY_AFFECTED", "NOT_AFFECTED").index(
            item[1]["impact"]
        ),
    ):
        badge = IMPACT_BADGE.get(verdict["impact"], verdict["impact"])
        lines = [f"{badge} — {_link(entry)}"]
        reason = str(verdict.get("reason", "")).strip()
        if reason:
            lines.append(f"  {html.escape(reason)}")
        action = str(verdict.get("action", "")).strip()
        if action and verdict["impact"] != "NOT_AFFECTED":
            lines.append(f"  ➡️ {html.escape(action)}")
        hotspots = [str(spot) for spot in verdict.get("hotspots", [])][:5]
        if hotspots:
            lines.append("  " + html.escape(", ".join(hotspots)))
        blocks.append("\n".join(lines))

    rest = [entry for entry in entries if entry.uid not in assessed]
    if rest:
        if blocks:
            blocks.append("<b>Other updates</b>")
        blocks.extend(f"• {_link(entry)}" for entry in rest)

    return blocks


def main():
    if not config.BOT_TOKEN or not config.CHAT_ID:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set.")

    entries = changelog.fetch_recent_entries()
    if not entries:
        notifier.send(
            "<b>🚀 Atlassian Developer Updates</b>\n\n"
            "No new release notes published in the last 24 hours. 💤"
        )
        return

    analysis = []
    if config.ANALYSIS_ENABLED:
        try:
            analysis = analyse(entries, bitbucket.sync_repositories())
        except RuntimeError as error:
            print(f"Impact analysis unavailable: {error}", file=sys.stderr)
            analysis = []
    else:
        print(
            "Impact analysis disabled "
            "(needs BITBUCKET_WORKSPACE, BITBUCKET_TOKEN and LLM_API_KEY)."
        )

    header = "<b>🚀 Atlassian Developer Updates (Last 24h)</b>"
    for message in notifier.split_messages(render_blocks(entries, analysis), header):
        notifier.send(message)


if __name__ == "__main__":
    main()
