"""
SHARED: GitHub-repos-as-stocks pricing + metrics fetch.
=======================================================

Goal: A single, plain-Python module that:
  - knows the fake "price" formula
  - knows how to fetch the live numbers from GitHub

Reused across all three polyglot-pong versions. Keeping this dependency-free
(standard library only) means every version can import it without a shared
venv — the *integration pattern* is the variable, the domain logic is the
constant.

Smoke test:
    python ticker_logic.py vercel/next.js

If you don't set GITHUB_TOKEN, you get 60 requests/hour. Set it and you get
5000. For a 20-repo watchlist polled every 30s, you need the token.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

GITHUB_API = "https://api.github.com"


@dataclass
class RepoMetrics:
    repo: str
    stars: int
    forks_this_week: int
    commits_today: int
    open_issues: int
    fetched_at: str  # ISO8601 UTC


class GitHubError(RuntimeError):
    """Anything that goes wrong talking to GitHub. The host should surface
    this to the user, not crash the worker."""


def price(m: RepoMetrics) -> int:
    """The fake stock price formula from the README.

    The number is meaningless in absolute terms — but it CHANGES OVER TIME
    as stars roll in, commits land, issues open and close. That's the whole
    point: real signal, fake P/L.
    """
    return (
        m.stars
        + 10 * m.forks_this_week
        + 100 * m.commits_today
        - 5 * m.open_issues
    )


def _request(path: str, params: dict[str, str] | None = None) -> dict | list:
    """One small wrapper around urllib so the rest of the file reads cleanly."""
    url = f"{GITHUB_API}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "polyglot-pong",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise GitHubError(
            f"GitHub {e.code} on {path}: {e.read().decode()[:200]}"
        ) from e
    except urllib.error.URLError as e:
        raise GitHubError(f"network error on {path}: {e.reason}") from e


def fetch_repo_metrics(repo: str) -> RepoMetrics:
    """Fetch the live numbers needed to compute price(repo).

    `repo` is "owner/name", e.g. "vercel/next.js".

    Three GitHub API calls per repo:
      1. /repos/{repo}              → stars, open_issues
      2. /repos/{repo}/forks        → forks_this_week (filtered client-side)
      3. /repos/{repo}/commits      → commits_today (server-side `since`)
    """
    if "/" not in repo:
        raise ValueError(f"expected 'owner/name', got {repo!r}")

    base = _request(f"/repos/{repo}")
    assert isinstance(base, dict)

    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    # Forks API doesn't filter by date server-side; we ask for newest and
    # count only those within the last 7 days. per_page=100 is enough for
    # repos that aren't getting forked thousands of times a week.
    forks = _request(f"/repos/{repo}/forks", {"sort": "newest", "per_page": "100"})
    assert isinstance(forks, list)
    forks_this_week = sum(1 for f in forks if f.get("created_at", "") >= week_ago)

    commits = _request(
        f"/repos/{repo}/commits", {"since": today_start, "per_page": "100"}
    )
    assert isinstance(commits, list)
    commits_today = len(commits)

    return RepoMetrics(
        repo=repo,
        stars=base.get("stargazers_count", 0),
        forks_this_week=forks_this_week,
        commits_today=commits_today,
        # GH's open_issues_count includes PRs; close enough for fake stocks.
        open_issues=base.get("open_issues_count", 0),
        fetched_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def metrics_to_dict(m: RepoMetrics) -> dict:
    """Serializable form. The price is computed once and bundled in so
    consumers (any of the three versions) don't have to re-import the
    formula."""
    return {
        "repo": m.repo,
        "stars": m.stars,
        "forks_this_week": m.forks_this_week,
        "commits_today": m.commits_today,
        "open_issues": m.open_issues,
        "fetched_at": m.fetched_at,
        "price": price(m),
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "vercel/next.js"
    m = fetch_repo_metrics(target)
    print(json.dumps(metrics_to_dict(m), indent=2))
