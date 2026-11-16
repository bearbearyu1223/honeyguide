"""Refresh: what happened to each saved claim between the commit it was checked at and now.

States per claim: ``unchanged``; ``moved`` (same lines, new numbers or path); ``stale`` (cited lines changed:
never served as fact until re-checked); ``retired`` (code gone); ``unanchored`` (no code anchors, untouched).
Plus ``uncovered``: new or changed Python units in changed files that no live claim cites, for the
Cartographer to map. Each anchor refreshes from its own commit; git is only asked for diffs and file contents.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from .anchors import CodeAnchor, Relocation, relocate
from .gitio import Repo
from .outline import Unit, line_hash, python_units

LIVE = ("unchanged", "moved", "stale")
CLAIM_STATES = ("unchanged", "moved", "stale", "retired", "unanchored")


@dataclass(frozen=True)
class AnchorResult:
    old: CodeAnchor
    path: str                 # path at the target (renames followed)
    reloc: Relocation
    candidate_hash: str | None = None   # hash of the candidate lines at the target, when stale with a location

    @property
    def state(self) -> str:
        return self.reloc.state


@dataclass(frozen=True)
class ClaimResult:
    claim_id: str
    response_id: str | None   # None for a map claim
    state: str
    anchors: tuple[AnchorResult, ...]

    @property
    def reason(self) -> str:
        return "; ".join(sorted({a.reloc.reason for a in self.anchors
                                 if a.state in ("stale", "retired") and a.reloc.reason}))


@dataclass(frozen=True)
class UncoveredUnit:
    path: str
    qualname: str
    kind: str
    start: int
    end: int
    change: str               # new or changed


@dataclass
class RefreshPlan:
    target: str
    base: str | None
    claims: list[ClaimResult] = field(default_factory=list)
    uncovered: list[UncoveredUnit] = field(default_factory=list)
    unoutlined: list[str] = field(default_factory=list)   # changed non-Python (or unparseable) files
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        found = Counter(c.state for c in self.claims)
        return {state: found.get(state, 0) for state in CLAIM_STATES}


def combine(states: Iterable[str]) -> str:
    """One claim's state from its anchors' states."""
    states = list(states)
    if not states:
        return "unanchored"
    if all(s == "unchanged" for s in states):
        return "unchanged"
    if all(s in ("unchanged", "moved") for s in states):
        return "moved"
    if all(s == "retired" for s in states):
        return "retired"
    return "stale"


class _Diffs:
    """``git diff --name-status -M`` from each base commit to the target, computed once per base."""

    def __init__(self, repo: Repo, target: str) -> None:
        self.repo, self.target = repo, target
        self._maps: dict[str, dict[str, tuple[str, str]]] = {}
        self._known: dict[str, bool] = {}

    def known(self, commit: str) -> bool:
        """Whether this clone has ``commit`` (an import from another clone may cite one it lacks)."""
        if commit not in self._known:
            self._known[commit] = self.repo.git("cat-file", "-t", commit, check=False).strip() == "commit"
        return self._known[commit]

    def change(self, base: str, path: str) -> tuple[str, str] | None:
        """``(letter, path at target)`` if ``path`` changed between ``base`` and the target, else None."""
        if base == self.target:
            return None
        if base not in self._maps:
            changes = {}
            for letter, old, new in self.repo.diff_name_status(base, self.target):
                if letter == "R":
                    changes[old] = ("R", new)
                elif letter in "MDT":
                    changes[old] = (letter, old)
            self._maps[base] = changes
        return self._maps[base].get(path)


def refresh_anchor(repo: Repo, diffs: _Diffs, anchor: CodeAnchor,
                   units_cache: dict[tuple[str, str], list[Unit]]) -> AnchorResult:
    if not diffs.known(anchor.commit):
        return AnchorResult(anchor, anchor.path, Relocation(
            "stale", reason=f"commit {anchor.commit[:12]} is not in this clone; fetch it, then refresh"))
    change = diffs.change(anchor.commit, anchor.path)
    if change is None:
        return AnchorResult(anchor, anchor.path, Relocation("unchanged", anchor.start, anchor.end,
                                                            anchor.symbol))
    letter, new_path = change
    if letter == "D":
        return AnchorResult(anchor, anchor.path, Relocation("retired", reason="file deleted"))
    lines = repo.lines_at(diffs.target, new_path)
    key = (diffs.target, new_path)
    if key not in units_cache:
        units_cache[key] = python_units(lines) if lines is not None and new_path.endswith(".py") else []
    reloc = relocate(anchor, lines, new_path, units_cache[key])
    cand = None
    if reloc.state == "stale" and reloc.start is not None and reloc.end is not None and lines is not None:
        cand = line_hash(lines[reloc.start - 1:reloc.end])
    return AnchorResult(anchor, new_path, reloc, cand)


def plan_refresh(repo: Repo, claims: Iterable[tuple[str | None, dict]], target: str = "HEAD",
                 base: str | None = None) -> RefreshPlan:
    """Classify every claim against ``target``; ``base`` (default: the most common anchor commit) is the
    commit the uncovered-code search diffs from."""
    target_sha = repo.rev(target)
    plan = RefreshPlan(target_sha, None)
    if target == "HEAD":
        dirty = repo.dirty()
        if dirty["tracked"]:
            plan.warnings.append(f"working tree has {dirty['tracked']} uncommitted change(s); "
                                 f"compared against HEAD {target_sha[:12]}, not the working tree")
    diffs = _Diffs(repo, target_sha)
    units_cache: dict[tuple[str, str], list[Unit]] = {}
    commits: Counter[str] = Counter()
    for response_id, claim in claims:
        if claim.get("freshness") == "retired":
            continue
        anchors = [CodeAnchor.from_dict(a) for a in claim.get("anchors", [])]
        results = tuple(refresh_anchor(repo, diffs, a, units_cache) for a in anchors)
        commits.update(a.commit for a in anchors if diffs.known(a.commit))
        plan.claims.append(ClaimResult(claim["id"], response_id, combine(r.state for r in results), results))
    if base and not diffs.known(base):
        plan.warnings.append(f"base {base[:12]} is not in this clone; diffing from the claims' commit instead")
        base = None
    plan.base = repo.rev(base) if base else (commits.most_common(1)[0][0] if commits else None)
    if plan.base and plan.base != target_sha:
        plan.uncovered, plan.unoutlined = find_uncovered(repo, plan.base, target_sha, plan.claims, units_cache)
    return plan


def find_uncovered(repo: Repo, base: str, target: str, results: list[ClaimResult],
                   units_cache: dict[tuple[str, str], list[Unit]] | None = None,
                   ) -> tuple[list[UncoveredUnit], list[str]]:
    """New or changed units in files changed from ``base`` to ``target`` that no live anchor overlaps."""
    units_cache = {} if units_cache is None else units_cache
    covered: dict[str, set[int]] = {}
    for result in results:
        for a in result.anchors:
            if a.state in LIVE and a.reloc.start is not None and a.reloc.end is not None:
                covered.setdefault(a.path, set()).update(range(a.reloc.start, a.reloc.end + 1))
    uncovered: list[UncoveredUnit] = []
    unoutlined: list[str] = []
    for letter, old, new in repo.diff_name_status(base, target):
        if letter == "D":
            continue
        path = new or old
        lines = repo.lines_at(target, path)
        if not path.endswith(".py") or lines is None:
            unoutlined.append(path)
            continue
        key = (target, path)
        if key not in units_cache:
            units_cache[key] = python_units(lines)
        units = units_cache[key]
        if not units and any(line.strip() for line in lines):
            unoutlined.append(path)
            continue
        before: dict[str, set[str]] = {}   # qualname -> hashes: a qualname can name several units
        if letter != "A":
            old_lines = repo.lines_at(base, old)
            for u in (python_units(old_lines) if old_lines else []):
                before.setdefault(u.qualname, set()).add(u.hash)
        cited = covered.get(path, set())
        for unit in units:
            if unit.hash in before.get(unit.qualname, ()):
                continue
            own = _own_lines(unit, units)
            if own & cited:
                continue
            uncovered.append(UncoveredUnit(path, unit.qualname, unit.kind, unit.start, unit.end,
                                           "changed" if unit.qualname in before else "new"))
    return uncovered, unoutlined


def _own_lines(unit: Unit, units: list[Unit]) -> set[int]:
    lines = set(range(unit.start, unit.end + 1))
    if unit.kind == "class":
        for other in units:
            if other.kind == "method" and other.qualname.startswith(unit.qualname + "."):
                lines -= set(range(other.start, other.end + 1))
    return lines


def apply_result(claim: dict, result: ClaimResult, target: str) -> dict:
    """The claim as it should be saved after refresh (a new dict; the input is not changed)."""
    out = dict(claim)
    if result.state == "unanchored":
        return out
    if result.state in ("unchanged", "moved"):
        out["anchors"] = [a.old.moved_to(a.path, a.reloc.start, a.reloc.end, target, a.reloc.symbol).to_dict()
                          for a in result.anchors]
        out["freshness"], out["freshness_reason"] = "current", ""
        out.pop("candidates", None)
        return out
    out["freshness"] = result.state
    out["freshness_reason"] = result.reason
    out["refreshed_to"] = target
    if result.state == "stale":
        candidates = [{"path": a.path, "start": a.reloc.start, "end": a.reloc.end,
                       "symbol": a.reloc.symbol, "state": a.state, "hash": a.candidate_hash}
                      for a in result.anchors if a.reloc.start is not None]
        # A claim already stale, re-checked by the Checker against the same candidate lines, keeps that
        # verdict; anything newly stale, or whose candidates moved, waits for a re-check again.
        if claim.get("freshness") != "stale" or claim.get("candidates") != candidates:
            out["check"] = "unchecked"
        out["candidates"] = candidates
    return out


def apply_plan(store, plan: RefreshPlan) -> list[str]:
    """Save the plan's outcome: anchors updated, stale and retired claims marked, the map's commit advanced.

    One hold of the lock for both files. ``plan`` may be older than the store: a claim whose anchors changed
    since it was planned (re-anchored by the Checker, say), or that was retired meanwhile, is left as it is and
    its id returned; the map's commit advances only if no map claim was skipped. Re-plan to cover those.
    """
    by_id = {r.claim_id: r for r in plan.claims}
    skipped: list[str] = []

    def fix(claims: list[dict]) -> list[dict]:
        out = []
        for claim in claims:
            result = by_id.get(claim["id"])
            if result is None:
                out.append(claim)
            elif (claim.get("freshness") == "retired"
                  or [CodeAnchor.from_dict(a) for a in claim.get("anchors", [])] != [a.old for a in result.anchors]):
                skipped.append(claim["id"])
                out.append(claim)
            else:
                out.append(apply_result(claim, result, plan.target))
        return out

    with store.locked():
        map_layer, answers = store.load("map"), store.load("answers")
        map_layer["claims"] = fix(map_layer["claims"])
        map_skipped = bool(skipped)
        for response in answers["responses"]:
            response["claims"] = fix(response["claims"])
        if not map_skipped:
            map_layer["commit"] = plan.target
        store.write_held("answers", answers)
        store.write_held("map", map_layer)
    return skipped
