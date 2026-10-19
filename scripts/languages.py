#!/usr/bin/env python3
"""Render metrics.languages.svg: the languages I work in, weighted by my commits.

For every repository I own, collaborate on or am an organization member of
(private ones included), count my commits and read the repository's language
byte counts. Each repository contributes its language SHARES weighted by my
commit count there, so a large repository I committed to once does not drown
out the ones I actually work in. Only aggregate percentages are written; no
repository names leave the run.

Needs GITHUB_TOKEN (a classic token with `repo` and `read:org`) and
GITHUB_LOGIN. Standard library only. Usage: python3 scripts/languages.py out.svg
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

API = "https://api.github.com"
# Every language is shown: no ignore list, no limit, no "Other" bucket.

# GitHub's linguist colours for the languages likely to show.
COLORS = {
    "Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Swift": "#F05138", "Rust": "#dea584", "Go": "#00ADD8", "Kotlin": "#A97BFF",
    "C": "#555555", "C++": "#f34b7d", "Shell": "#89e051", "Dockerfile": "#384d54",
    "HCL": "#844FBA", "Rhai": "#ffdd00", "GDScript": "#355570", "SQL": "#e38c00",
    "Makefile": "#427819", "Objective-C": "#438eff", "Java": "#b07219",
    "PLpgSQL": "#336790", "Ruby": "#701516", "HTML": "#e34c26", "CSS": "#563d7c",
    "SCSS": "#c6538c", "Jupyter Notebook": "#DA5B0B", "MDX": "#fcb32c",
    "Svelte": "#ff3e00", "Vue": "#41b883", "Lua": "#000080", "PowerShell": "#012456",
    "Batchfile": "#C1F12E", "Starlark": "#76d275", "Nix": "#7e7eff",
    "Jinja": "#a52a22", "Mustache": "#724b3b", "Smarty": "#f0c040",
}
# Unknown languages get a stable colour from this palette instead of grey.
FALLBACK = ["#8e44ad", "#16a085", "#d35400", "#2c3e50", "#c0392b", "#27ae60",
            "#7f8c8d", "#2980b9", "#f39c12", "#6d4c41"]


def color(name: str) -> str:
    if name in COLORS:
        return COLORS[name]
    return FALLBACK[sum(name.encode()) % len(FALLBACK)]


def percent(share: float) -> str:
    return "<0.1%" if share < 0.001 else f"{share * 100:.1f}%"


def get(url: str, token: str, attempts: int = 4) -> tuple[object, dict[str, str]]:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
                return (json.loads(body) if body else None), dict(response.headers)
        except urllib.error.HTTPError as error:
            if error.code in (404, 409):  # gone, or an empty repository
                return None, {}
            if error.code < 500 or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def repositories(token: str) -> list[str]:
    names, page = [], 1
    while True:
        batch, _ = get(f"{API}/user/repos?per_page=100&page={page}"
                       "&affiliation=owner,collaborator,organization_member", token)
        if not batch:
            return names
        names += [repo["full_name"] for repo in batch if not repo.get("fork")]
        page += 1


def my_commit_count(repo: str, login: str, token: str) -> int:
    """Commits authored by `login` on the default branch (one request)."""
    commits, headers = get(f"{API}/repos/{repo}/commits?author={login}&per_page=1", token)
    if not commits:
        return 0
    last = re.search(r'[?&]page=(\d+)>; rel="last"', headers.get("Link", ""))
    return int(last.group(1)) if last else len(commits)


def weighted_languages(token: str, login: str) -> Counter:
    totals: Counter = Counter()
    for repo in repositories(token):
        commits = my_commit_count(repo, login, token)
        if not commits:
            continue
        languages, _ = get(f"{API}/repos/{repo}/languages", token)
        size = sum((languages or {}).values())
        for name, part in (languages or {}).items():
            totals[name] += commits * part / size
    return totals


def shares(totals: Counter) -> list[tuple[str, float]]:
    grand = sum(totals.values())
    if not grand:
        return []
    return [(name, value / grand) for name, value in totals.most_common()]


def render(rows: list[tuple[str, float]]) -> str:
    width, bar_y, bar_h = 600, 4, 10
    columns, row_h, legend_y = 3, 22, 34
    height = legend_y + -(-len(rows) // columns) * row_h + 6
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Languages I work in">',
        "<style>text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,"
        "sans-serif;font-size:13px;fill:#777}</style>",
    ]
    if not rows:
        parts.append('<text x="0" y="16">No commits found yet</text></svg>')
        return "".join(parts)
    x = 0.0
    parts.append(f'<clipPath id="r"><rect x="0" y="{bar_y}" width="{width}" '
                 f'height="{bar_h}" rx="5"/></clipPath><g clip-path="url(#r)">')
    for name, share in rows:
        w = share * width
        parts.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{w + 0.5:.2f}" '
                     f'height="{bar_h}" fill="{color(name)}"/>')
        x += w
    parts.append("</g>")
    for i, (name, share) in enumerate(rows):
        cx = (i % columns) * (width // columns)
        cy = legend_y + (i // columns) * row_h
        parts.append(f'<circle cx="{cx + 6}" cy="{cy - 4}" r="5" fill="{color(name)}"/>')
        parts.append(f'<text x="{cx + 18}" y="{cy}">{html.escape(name)} '
                     f'<tspan fill="#999">{html.escape(percent(share))}</tspan></text>')
    parts.append("</svg>")
    return "".join(parts)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: languages.py <out.svg>", file=sys.stderr)
        return 2
    token, login = os.environ["GITHUB_TOKEN"], os.environ["GITHUB_LOGIN"]
    rows = shares(weighted_languages(token, login))
    with open(argv[0], "w", encoding="utf-8") as out:
        out.write(render(rows))
    for name, share in rows:
        print(f"  {name:<18} {percent(share):>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
