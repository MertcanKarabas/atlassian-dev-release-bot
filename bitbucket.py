"""List and mirror Bitbucket Cloud repositories so they can be searched locally."""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

import config

API_ROOT = "https://api.bitbucket.org/2.0"


@dataclass
class Repo:
    slug: str
    branch: str
    path: Path


def _auth():
    """Return (rest_kwargs, clone_username) for the configured token flavour."""
    if not config.BITBUCKET_TOKEN:
        raise RuntimeError("BITBUCKET_TOKEN is not set.")
    if config.BITBUCKET_EMAIL:
        # Atlassian account API token: Basic email:token, clone as x-bitbucket-api-token-auth.
        return (
            {"auth": (config.BITBUCKET_EMAIL, config.BITBUCKET_TOKEN)},
            "x-bitbucket-api-token-auth",
        )
    # Repository / project / workspace access token: Bearer, clone as x-token-auth.
    return (
        {"headers": {"Authorization": f"Bearer {config.BITBUCKET_TOKEN}"}},
        "x-token-auth",
    )


def _redact(text):
    return (text or "").replace(config.BITBUCKET_TOKEN, "***") if config.BITBUCKET_TOKEN else text


def _run_git(args, cwd=None):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise RuntimeError(_redact(result.stderr.strip() or result.stdout.strip()))
    return result.stdout


def list_repositories():
    """Return [(slug, default_branch)] for the workspace, honouring BITBUCKET_REPOS."""
    rest_kwargs, _ = _auth()
    url = (
        f"{API_ROOT}/repositories/{quote(config.BITBUCKET_WORKSPACE)}"
        "?pagelen=100&fields=next,values.slug,values.mainbranch.name"
    )

    repos = []
    while url:
        response = requests.get(url, timeout=60, **rest_kwargs)
        if not response.ok:
            raise RuntimeError(
                f"Bitbucket API {response.status_code}: {_redact(response.text)[:500]}"
            )
        payload = response.json()
        for value in payload.get("values", []):
            slug = value.get("slug")
            branch = (value.get("mainbranch") or {}).get("name") or "main"
            if slug:
                repos.append((slug, branch))
        url = payload.get("next")

    if config.BITBUCKET_REPOS:
        wanted = set(config.BITBUCKET_REPOS)
        missing = wanted - {slug for slug, _ in repos}
        if missing:
            print(f"Warning: repos not found in workspace: {', '.join(sorted(missing))}")
        repos = [item for item in repos if item[0] in wanted]

    return repos[: config.MAX_REPOS]


def sync_repositories():
    """Shallow-clone (or refresh) every selected repo and return the local checkouts."""
    _, clone_user = _auth()
    root = Path(config.CLONE_DIR)
    root.mkdir(parents=True, exist_ok=True)

    synced = []
    for slug, default_branch in list_repositories():
        branch = config.BITBUCKET_BRANCH or default_branch
        target = root / slug
        remote = (
            f"https://{clone_user}:{quote(config.BITBUCKET_TOKEN, safe='')}"
            f"@bitbucket.org/{config.BITBUCKET_WORKSPACE}/{slug}.git"
        )
        try:
            if (target / ".git").is_dir():
                _run_git(["fetch", "--depth", "1", remote, branch], cwd=target)
                _run_git(["checkout", "--force", "FETCH_HEAD"], cwd=target)
            else:
                _run_git(
                    [
                        "clone",
                        "--depth",
                        "1",
                        "--single-branch",
                        "--branch",
                        branch,
                        remote,
                        str(target),
                    ]
                )
        except RuntimeError as error:
            print(f"Skipping {slug}@{branch}: {error}", file=sys.stderr)
            continue

        synced.append(Repo(slug=slug, branch=branch, path=target))
        print(f"Synced {slug}@{branch}")

    if not synced:
        raise RuntimeError("No Bitbucket repositories could be synced.")
    return synced
