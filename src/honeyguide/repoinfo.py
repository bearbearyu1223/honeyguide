"""``honeyguide repo-info`` (T7.18): what the map page's repo card shows, gathered at map time.

From git, at one commit (the map's): the remote as an https link, the default branch, the commit and its date, the
first and last commit dates, the commit count, languages by share (lines of tracked source, by extension, top 5 +
other), the licence (an SPDX id guessed from the licence file's text, and the file), the top contributors by commit
count (``git shortlog -sne``; names only, never emails) and the README's title and description line (with its path
and line, so an agent can cite it as a ``docs`` claim).

From GitHub, only when ``gh`` is installed and signed in and the remote is on github.com: stars, forks, open issues,
topics and description (``gh api repos/<owner>/<repo>``), stamped "as of" the UTC date they were read. Otherwise
those fields are absent and ``github_note`` says why. Nothing else touches the network, and the page never fetches:
it renders what is stored in the map document (``document.repo``).

These are metadata with their provenance, not claims: they can't be re-checked against lines at a commit (GitHub
counts change daily; commit counts and dates are history, not code). The Cartographer cites the README and licence
lines as ``docs`` claims and leaves counts to the card (docs/design/agent-contract.md, "Repo info").
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone

from .gitio import Repo
from .repoid import choose_remote, github_slug, normalize_remote

SCHEMA = 1
TOP_LANGUAGES = 5
TOP_CONTRIBUTORS = 5

# extension -> language, for lines of tracked source (docs, data, lockfiles and notebooks are not counted)
LANGUAGES = {
    "py": "Python", "pyx": "Cython", "pyi": "Python", "js": "JavaScript", "mjs": "JavaScript", "cjs": "JavaScript",
    "jsx": "JavaScript", "ts": "TypeScript", "tsx": "TypeScript", "go": "Go", "rs": "Rust", "c": "C", "h": "C",
    "cc": "C++", "cpp": "C++", "cxx": "C++", "hh": "C++", "hpp": "C++", "cu": "CUDA", "cuh": "CUDA", "java": "Java",
    "kt": "Kotlin", "kts": "Kotlin", "scala": "Scala", "swift": "Swift", "m": "Objective-C", "mm": "Objective-C",
    "rb": "Ruby", "php": "PHP", "cs": "C#", "fs": "F#", "lua": "Lua", "jl": "Julia", "r": "R", "zig": "Zig",
    "sh": "Shell", "bash": "Shell", "zsh": "Shell", "ex": "Elixir", "exs": "Elixir", "erl": "Erlang", "hs": "Haskell",
    "ml": "OCaml", "dart": "Dart", "vue": "Vue", "svelte": "Svelte", "sql": "SQL", "html": "HTML", "css": "CSS",
    "scss": "SCSS",
}
SKIP_DIRS = ("node_modules/", "vendor/", "third_party/", "dist/", "build/")

# (SPDX id, phrases that must all appear in the licence text, lowercased and whitespace-collapsed), most specific first
LICENSES = [
    ("AGPL-3.0", ["gnu affero general public license", "version 3"]),
    ("LGPL-3.0", ["gnu lesser general public license", "version 3"]),
    ("LGPL-2.1", ["gnu lesser general public license", "version 2.1"]),
    ("GPL-3.0", ["gnu general public license", "version 3"]),
    ("GPL-2.0", ["gnu general public license", "version 2"]),
    ("Apache-2.0", ["apache license", "version 2.0"]),
    ("MPL-2.0", ["mozilla public license", "2.0"]),
    ("Elastic-2.0", ["elastic license 2.0"]),
    ("BSD-3-Clause", ["redistribution and use in source and binary forms", "neither the name"]),
    ("BSD-2-Clause", ["redistribution and use in source and binary forms"]),
    ("MIT", ["permission is hereby granted, free of charge", "the above copyright notice"]),
    ("ISC", ["permission to use, copy, modify, and/or distribute this software for any purpose"]),
    ("Unlicense", ["this is free and unencumbered software released into the public domain"]),
    ("BSL-1.0", ["boost software license"]),
]
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying)(\.(md|txt|rst))?$", re.IGNORECASE)
README_FILE = re.compile(r"^readme(\.(md|markdown|rst|txt))?$", re.IGNORECASE)


def https_link(url: str | None) -> str | None:
    """A remote as a browsable https link (credentials, ``.git`` and ports dropped); None for a local path."""
    normalized = normalize_remote(url) if url else None
    if not normalized:
        return None
    slug = github_slug(url)
    if slug:
        return f"https://github.com/{slug[0]}/{slug[1]}"
    return f"https://{normalized}"


def guess_license(text: str) -> str | None:
    flat = " ".join(text.lower().split())
    for spdx, phrases in LICENSES:
        if all(p in flat for p in phrases):
            return spdx
    return None


def language_shares(counts: dict[str, int], top: int = TOP_LANGUAGES) -> list[dict]:
    """``[{name, lines, share}]``, largest first, the rest folded into "Other"; shares are fractions of all lines,
    rounded to 3 places, so they sum to 1 within rounding."""
    total = sum(counts.values())
    if not total:
        return []
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out = [{"name": k, "lines": v, "share": round(v / total, 3)} for k, v in ranked[:top]]
    rest = sum(v for _, v in ranked[top:])
    if rest:
        out.append({"name": "Other", "lines": rest, "share": round(rest / total, 3)})
    return out


def parse_shortlog(text: str, top: int = TOP_CONTRIBUTORS) -> tuple[list[dict], int]:
    """``git shortlog -sne`` lines -> the top contributors by commits, NAMES ONLY (one person with several emails
    counts once, and one email under several names counts once, under its most used name), and how many distinct
    people that leaves. The emails are used only to join; they are never returned."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s+(.*?)\s*(<[^>]*>)?\s*$", line)
        if m and m.group(2):
            rows.append((int(m.group(1)), m.group(2).strip(), (m.group(3) or "").lower()))
    # union names that share an email
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x
    first_name: dict[str, str] = {}
    for _, name, email in rows:
        find(name)
        if email and email != "<>":
            if email in first_name:
                parent[find(name)] = find(first_name[email])
            else:
                first_name[email] = name
    per_name: Counter = Counter()
    for n, name, _ in rows:
        per_name[name] += n
    groups: dict[str, list[str]] = {}
    for name in per_name:
        groups.setdefault(find(name), []).append(name)
    by_name: Counter = Counter()
    for names in groups.values():
        best = max(names, key=lambda x: (per_name[x], len(x)))
        by_name[best] = sum(per_name[x] for x in names)
    ranked = sorted(by_name.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [{"name": n, "commits": c} for n, c in ranked[:top]], len(by_name)


def readme_summary(lines: list[str]) -> dict:
    """The README's title (its first heading) and description (the first prose line after it: no badges, HTML,
    headings or blank lines), each with its 1-based line number."""
    out: dict = {}
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if "title" not in out and heading:
            out["title"], out["title_line"] = heading.group(1).strip(), i
            continue
        if heading or line.startswith(("<", "[![", "![", "---", "===", "```", "|", ">")) or re.match(r"^[=\-~^]{3,}$", line):
            continue
        if "title" not in out and i < len(lines) and re.match(r"^[=\-]{3,}$", lines[i].strip()):   # setext heading
            out["title"], out["title_line"] = line, i
            continue
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)          # links keep their words
        text = re.sub(r"[*_`]", "", text).strip()
        if len(text) < 12:
            continue
        if len(text) > 280:   # whole sentences when it is long; a word boundary and an ellipsis only as a fallback
            cut = text[:280].rfind(". ")
            text = text[:cut + 1] if cut > 60 else text[:279].rsplit(" ", 1)[0] + "…"
        out["description"], out["description_line"] = text, i
        break
    return out


def _gh_ready(gh: str | None) -> str | None:
    """None if ``gh`` can be used, else why not."""
    if os.environ.get("HONEYGUIDE_NO_GH"):
        return "GitHub counts not fetched: HONEYGUIDE_NO_GH is set"
    if not gh:
        return "GitHub counts not fetched: gh is not installed"
    try:
        proc = subprocess.run([gh, "auth", "status"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return "GitHub counts not fetched: gh did not run"
    if proc.returncode != 0:
        return "GitHub counts not fetched: gh is not signed in (gh auth login)"
    return None


def github_info(gh: str | None, owner: str, name: str, today: str) -> tuple[dict | None, str | None]:
    why = _gh_ready(gh)
    if why:
        return None, why
    try:
        proc = subprocess.run([gh, "api", f"repos/{owner}/{name}"], capture_output=True, text=True, timeout=30)
        data = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        return None, "GitHub counts not fetched: gh api failed"
    return {"stars": data.get("stargazers_count"), "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"), "topics": list(data.get("topics") or []),
            "description": data.get("description") or None, "as_of": today}, None


def repo_info(repo: Repo, commit: str = "HEAD", gh: str | None = "auto", now: datetime | None = None) -> dict:
    """Everything the repo card shows, at ``commit``. ``gh``: the gh executable ("auto": from PATH; None: never)."""
    sha = repo.rev(commit)
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = when.strftime("%Y-%m-%d")
    chosen = choose_remote(repo.remotes())
    remote_url = chosen[1] if chosen else None
    normalized = normalize_remote(remote_url) if remote_url else None
    slug = github_slug(remote_url) if remote_url else None
    name = "/".join(slug) if slug else (normalized.split("/", 1)[1] if normalized and "/" in normalized
                                        else repo.root.name)
    info: dict = {"schema": SCHEMA, "name": name, "url": https_link(remote_url), "host": normalized.split("/")[0]
                  if normalized else None, "generated_at": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
    branch = repo.git("symbolic-ref", "--quiet", "--short", f"refs/remotes/{chosen[0]}/HEAD", check=False).strip() \
        if chosen else ""
    if branch and "/" in branch:
        branch = branch.split("/", 1)[1]
    if not branch:
        branch = repo.git("symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
    info["default_branch"] = branch or None
    info["commit"] = {"sha": sha, "date": repo.git("show", "-s", "--format=%cI", sha).strip()}
    roots = repo.git("log", "--max-parents=0", "--format=%aI", sha).split()
    info["first_commit_date"] = min(roots) if roots else None
    info["last_commit_date"] = info["commit"]["date"]
    info["commits"] = int(repo.git("rev-list", "--count", sha).strip() or 0)
    # languages: lines of tracked source at the commit, by extension
    counts: Counter = Counter()
    files = repo.ls_files(sha)
    # one `git grep -c ''` over the commit: lines per text file (binary files are skipped by -I)
    for line in repo.git("grep", "-I", "-z", "-c", "", sha, check=False).split("\n"):
        where, sep, n = line.rpartition("\0")
        if not sep or not n.strip().isdigit():
            continue
        path = where.split(":", 1)[1] if where.startswith(sha + ":") else where
        if any(path.startswith(d) or f"/{d}" in path for d in SKIP_DIRS):
            continue
        base = path.rsplit("/", 1)[-1]
        ext = base.rsplit(".", 1)[-1] if "." in base else ""
        lang = LANGUAGES.get(ext) or LANGUAGES.get(ext.lower())
        if lang:
            counts[lang] += int(n)
    info["languages"] = language_shares(counts)
    info["source_lines"] = sum(counts.values())
    top = [p for p in files if "/" not in p]
    lic = next((p for p in sorted(top) if LICENSE_FILE.match(p)), None)
    info["license"] = {"spdx": guess_license("\n".join(repo.lines_at(sha, lic) or [])) if lic else None, "file": lic}
    people, total = parse_shortlog(repo.git("shortlog", "-sne", sha, check=False))
    info["contributors"] = people
    info["contributor_count"] = total
    readme = next((p for p in sorted(top, key=lambda p: (not p.lower().endswith(".md"), p)) if README_FILE.match(p)), None)
    info["readme"] = {"path": readme, **readme_summary(repo.lines_at(sha, readme) or [])} if readme else None
    if gh == "auto":
        gh = shutil.which("gh")
    if slug and info["host"] == "github.com":
        info["github"], note = github_info(gh, slug[0], slug[1], today)
    else:
        info["github"], note = None, "GitHub counts not fetched: the remote is not on GitHub"
    if note:
        info["github_note"] = note
    return info


def check_repo_info(info: object, where: str = "document.repo") -> list[str]:
    """The shape the page relies on; a stored card that doesn't fit is an error, never half-rendered."""
    if not isinstance(info, dict):
        return [f"{where}: must be an object (honeyguide repo-info output)"]
    errors = []
    if not isinstance(info.get("name"), str) or not info["name"]:
        errors.append(f"{where}.name: required")
    if not isinstance(info.get("languages", []), list):
        errors.append(f"{where}.languages: must be a list")
    for p in info.get("contributors") or []:
        if not isinstance(p, dict) or "@" in str(p.get("name", "")) or "email" in p:
            errors.append(f"{where}.contributors: names only (no emails)")
            break
    gh = info.get("github")
    if gh is not None and (not isinstance(gh, dict) or not gh.get("as_of")):
        errors.append(f"{where}.github: needs its as_of date")
    return errors
