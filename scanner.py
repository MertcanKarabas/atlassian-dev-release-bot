"""Turn a changelog entry into search terms and hunt for them in the checkouts."""

import re
import subprocess
from dataclasses import dataclass

import config

# Code-shaped things worth grepping for, pulled straight from the entry markup.
CODE_TAG = re.compile(r"<code[^>]*>(.*?)</code>", re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]+>")
PATTERNS = (
    re.compile(r"@[a-z0-9-]+/[a-z0-9._-]+"),                  # @atlaskit/icon-object
    re.compile(r"/(?:rest|wiki|ex|gateway)/[A-Za-z0-9/_.{}-]+"),  # /rest/api/3/issue
    re.compile(r"\b[a-z]+:[a-zA-Z][a-zA-Z0-9-]{3,}\b"),        # read:jira-work, jira:issuePanel
    re.compile(r"\b[a-z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*){1,}\b"),  # workflowEntityId
)

# Words that are code-shaped but match half the internet.
STOPWORDS = {
    "atlassian", "bitbucket", "confluence", "jira", "forge", "connect", "marketplace",
    "javaScript", "typeScript", "gitHub", "readMe", "changeLog", "isNew", "isOld",
    "http", "https", "json", "html", "api", "apis", "url", "urls", "uuid",
    "developer", "cloud", "server", "webhook", "webhooks", "endpoint", "endpoints",
}

EXCLUDE_PATHSPECS = [
    ":(exclude)*.lock",
    ":(exclude)*-lock.json",
    ":(exclude)*.min.js",
    ":(exclude)*.map",
    ":(exclude)dist/*",
    ":(exclude)build/*",
    ":(exclude)vendor/*",
    ":(exclude)node_modules/*",
]


@dataclass
class Match:
    repo: str
    path: str
    line_no: int
    line_text: str
    term: str

    @property
    def location(self):
        return f"{self.repo}/{self.path}:{self.line_no}"


def _clean(term):
    term = TAG.sub("", term).strip().strip("`.,;:()[]\"'")
    return term


def candidate_terms(entry, limit=12):
    """Extract greppable identifiers from an entry, most specific first."""
    haystack = f"{entry.title}\n{entry.raw_html}"

    tiered = []
    for raw in CODE_TAG.findall(haystack):
        tiered.append((0, _clean(raw)))
    for tier, pattern in enumerate(PATTERNS, start=1):
        for raw in pattern.findall(TAG.sub(" ", haystack)):
            tiered.append((tier, _clean(raw)))

    seen = set()
    terms = []
    for _, term in sorted(tiered, key=lambda item: item[0]):
        if len(term) < 5 or " " in term or term.lower() in STOPWORDS:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) >= limit:
            break
    return terms


def search(repos, terms):
    """Run `git grep` for every term across every checkout."""
    matches = []
    for term in terms:
        per_term = 0
        for repo in repos:
            if per_term >= config.MAX_MATCHES_PER_TERM:
                break
            result = subprocess.run(
                [
                    "git", "grep", "--no-color", "-n", "-I", "--fixed-strings",
                    "-e", term, "--", ".", *EXCLUDE_PATHSPECS,
                ],
                cwd=repo.path,
                capture_output=True,
                text=True,
            )
            # git grep exits 1 when nothing matched; anything higher is a real error.
            if result.returncode > 1:
                print(f"git grep failed in {repo.slug}: {result.stderr.strip()}")
                continue
            for line in result.stdout.splitlines():
                path, _, rest = line.partition(":")
                line_no, _, text = rest.partition(":")
                if not line_no.isdigit():
                    continue
                matches.append(
                    Match(
                        repo=repo.slug,
                        path=path,
                        line_no=int(line_no),
                        line_text=text.strip()[:200],
                        term=term,
                    )
                )
                per_term += 1
                if per_term >= config.MAX_MATCHES_PER_TERM:
                    break
    return matches[: config.MAX_MATCHES_PER_ENTRY]
