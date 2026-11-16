"""eval/human: Han's click-through page for the T5 / T6a / T6b chores.

- what the page shows matches the generated md sheets line for line (counts asserted against the files);
- answers round-trip through disk as stable sorted JSON with the MANIFEST hash recorded; a changed MANIFEST or a
  moved hop is detected, not silently carried over;
- the server refuses requests without the token, a foreign Host or a non-JSON POST, and serves the page under a CSP;
- in headless Chrome: a hop marked with the keyboard and a why/how question added both land in the answers files.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "human"))
import chores  # noqa: E402
import serve  # noqa: E402

QDIR = ROOT / "eval" / "questions"
REPOS = chores.repo_names()


def md_lines(repo, sheet, prefix):
    text = (QDIR / f"{repo}_{sheet}.md").read_text()
    return [line[len(prefix):] for line in text.splitlines() if line.startswith(prefix)]


def test_both_repos_found():
    assert REPOS == ["nanochat", "waku-agent"]


@pytest.mark.parametrize("repo", REPOS)
def test_hops_match_the_md_sheet(repo):
    fz = chores.load_frozen(repo)
    md = md_lines(repo, "flow_hops_to_mark", "- [ ] required [ ] optional: ")
    labels = [h["label"] for q in fz["flows"] for h in q["hops"]]
    assert len(labels) == len(md) > 0
    assert labels == md
    md_ids = re.findall(r"^## (\S+) \(", (QDIR / f"{repo}_flow_hops_to_mark.md").read_text(), re.M)
    assert [q["id"] for q in fz["flows"]] == md_ids
    assert "xN = times called" in fz["flow_intro"] and "**" not in fz["flow_intro"]


def test_hop_totals_are_the_sheet_totals():
    totals = {r: sum(len(q["hops"]) for q in chores.load_frozen(r)["flows"]) for r in REPOS}
    assert totals == {r: len(md_lines(r, "flow_hops_to_mark", "- [ ] required")) for r in REPOS}


@pytest.mark.parametrize("repo", REPOS)
def test_disputes_and_key_match_the_md_sheet(repo):
    fz = chores.load_frozen(repo)
    md = md_lines(repo, "callers_disputes", "- [ ] caller [ ] not: ")
    assert [d["label"] for q in fz["callers"] for d in q["disputes"]] == md
    assert len(md) == len(md_lines(repo, "callers_disputes", "- [ ] caller"))
    in_key = [line for line in md_lines(repo, "callers_disputes", "- ") if line.startswith("in key")]
    assert [k["label"] for q in fz["callers"] for k in q["in_key"]] == in_key
    md_kinds = md_lines(repo, "callers_disputes", "- ")[:len(fz["dispute_kinds"])]
    assert md_kinds == [f"{k}: {v}" for k, v in fz["dispute_kinds"].items()]


@pytest.mark.parametrize("repo", REPOS)
def test_pins_and_links_come_from_the_json(repo):
    data = json.loads((QDIR / f"{repo}.json").read_text())
    fz = chores.load_frozen(repo)
    assert fz["tree"] == f"{data['url']}/tree/{data['commit']}"
    assert fz["readme"] == f"{data['url']}/blob/{data['commit']}/README.md"
    hop = fz["flows"][0]["hops"][0]
    assert hop["link"] == f"{data['url']}/blob/{data['commit']}/{hop['file']}#L{hop['line']}"
    clone = Path.home() / "Documents" / "GitHub" / "honeyguide-targets" / repo
    if clone.exists():
        names = subprocess.run(["git", "-C", str(clone), "ls-tree", "--name-only", data["commit"]],
                               capture_output=True, text=True, check=True).stdout.split()
        assert chores.README in names


def test_frozen_sets_verify():
    assert chores.verify_manifest() == []


def test_round_trip_and_manifest_hash(tmp_path):
    a = chores.Answers(tmp_path)
    a.set_hop("nanochat", "nc-flo-01", 0, "required")
    a.set_hop("nanochat", "nc-flo-01", 2, "optional")
    a.set_dispute("waku-agent", "wk-cal-03", 1, "caller", "registry call")
    item = a.add_whyhow("nanochat")
    a.save_whyhow("nanochat", [dict(item, text="Why X?", rubric_must=["one", "two"], relevant="gpt.py")])

    b = chores.Answers(tmp_path)
    assert b.hops["nanochat"]["nc-flo-01"][:3] == ["required", None, "optional"]
    assert b.disputes["waku-agent"]["wk-cal-03"][1] == {"decision": "caller", "note": "registry call"}
    assert b.whyhow["nanochat"]["questions"][0]["text"] == "Why X?"
    manifest = chores.sha256_bytes((QDIR / "MANIFEST.txt").read_bytes())
    for name in ("hops_nanochat.json", "disputes_waku-agent.json", "whyhow_nanochat.json"):
        text = (tmp_path / name).read_text()
        doc = json.loads(text)
        assert doc["manifest_sha256"] == manifest
        assert text == chores.dumps(doc)            # stable sorted JSON
    ids = {q["id"] for q in json.loads((QDIR / "nanochat.json").read_text())["questions"]}
    assert set(json.loads((tmp_path / "hops_nanochat.json").read_text())["questions"]) <= ids
    assert b.stale == {}


def test_stale_manifest_and_moved_hop_are_detected(tmp_path):
    a = chores.Answers(tmp_path)
    a.set_hop("nanochat", "nc-flo-01", 0, "required")
    a.set_hop("nanochat", "nc-flo-01", 1, "required")
    path = tmp_path / "hops_nanochat.json"
    doc = json.loads(path.read_text())
    doc["manifest_sha256"] = "0" * 64
    doc["questions"]["nc-flo-01"]["hops"][1]["qual"] = "Somewhere.else"   # the key moved under this mark
    chores.write_json(path, doc)
    b = chores.Answers(tmp_path)
    assert b.stale == {"hops_nanochat.json": "0" * 64}
    assert b.hops["nanochat"]["nc-flo-01"][:2] == ["required", None]
    s = chores.summarize(tmp_path)
    assert s["repos"]["nanochat"]["stale_files"] == ["hops_nanochat.json"] and not s["repos"]["nanochat"]["done"]
    assert "STALE: hops_nanochat.json" in chores.summary_text(s)


def test_whyhow_ids_rules_and_validation(tmp_path):
    a = chores.Answers(tmp_path)
    q1, q2 = a.add_whyhow("nanochat"), a.add_whyhow("nanochat")
    assert (q1["id"], q2["id"]) == ("nc-why-01", "nc-why-02")
    a.save_whyhow("nanochat", [q2])                                       # delete q1
    assert a.add_whyhow("nanochat")["id"] == "nc-why-03"                  # never reused
    with pytest.raises(ValueError):
        a.save_whyhow("nanochat", [dict(q1, text="back from the dead")])
    with pytest.raises(ValueError):
        a.set_hop("nanochat", "nc-flo-01", 99, "required")
    with pytest.raises(ValueError):
        a.set_hop("nanochat", "nc-flo-01", 0, "maybe")
    assert chores.whyhow_problems(dict(q1, text="x", rubric_must=["a", " "])) == [
        "rubric has 1 bullet (needs 2-6)"]
    assert chores.whyhow_problems(dict(q1, text="x", rubric_must=["a", "b"])) == []
    assert chores.whyhow_problems(dict(q1, text="x", rubric_must=list("abcdef"))) == []
    assert chores.whyhow_problems(dict(q1, text="x", rubric_must=list("abcdefg"))) == [
        "rubric has 7 bullets (needs 2-6)"]


def test_summary_completes(tmp_path):
    a = chores.Answers(tmp_path)
    for r, fz in a.frozen.items():
        for q in fz["flows"]:
            for h in q["hops"]:
                a.set_hop(r, q["id"], h["index"], "required")
        a.set_hop(r, fz["flows"][0]["id"], 0, "excluded")             # an excluded hop counts as marked
        for q in fz["callers"]:
            for d in q["disputes"]:
                a.set_dispute(r, q["id"], d["index"], "not", "")
        items = [a.add_whyhow(r) for _ in range(chores.WHYHOW_MIN)]
        a.save_whyhow(r, [dict(i, text="q", rubric_must=["a", "b"]) for i in items])
    s = chores.summarize(tmp_path)
    assert s["done"]
    out = subprocess.run([sys.executable, str(ROOT / "eval" / "human" / "check.py"), "--answers", str(tmp_path)],
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.endswith("all complete: yes\n")
    n = len(md_lines("nanochat", "flow_hops_to_mark", "- [ ] required"))
    assert f"nanochat {n} of {n} hops marked ({n - 1} required, 0 optional, 1 excluded)" in out.stdout


# ---------- the server ----------

@pytest.fixture()
def site(tmp_path):
    answers = chores.Answers(tmp_path)
    server = serve.make_server(answers, port=0, token="ab" * 16)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield {"base": base, "token": "ab" * 16, "dir": tmp_path, "url": f"{base}/#t={'ab' * 16}"}
    server.shutdown()
    server.server_close()


def call(url, token=None, body=None, ctype="application/json", host=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode())
    if token:
        req.add_header("X-Honeyguide-Token", token)
    if body is not None:
        req.add_header("Content-Type", ctype)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_token_required(site):
    b, t = site["base"], site["token"]
    assert call(b + "/api/state")[0] == 403
    assert call(b + "/api/state", token="cd" * 16)[0] == 403
    assert call(b + "/api/state", token=t)[0] == 200
    hop = {"repo": "nanochat", "qid": "nc-flo-01", "index": 0, "mark": "required"}
    assert call(b + "/api/hop", body=hop)[0] == 403
    assert call(b + "/api/hop", token=t, body=hop, ctype="text/plain")[0] == 403
    assert call(b + "/api/state", token=t, host="evil.example:80")[0] == 403
    assert not (site["dir"] / "hops_nanochat.json").exists()
    assert call(b + "/api/hop", token=t, body=hop)[0] == 200
    assert (site["dir"] / "hops_nanochat.json").exists()
    status, headers, page = call(b + "/")
    assert status == 200 and "script-src 'self'" in headers["Content-Security-Policy"]
    assert t.encode() not in page and b"<style" not in page and b"style=" not in page
    assert not re.search(rb"<script>(?!</script>)", page)        # scripts by src only


# ---------- headless Chrome ----------

def test_keyboard_hop_and_add_whyhow_in_chrome(site):
    sys.path.insert(0, str(ROOT / "tests"))
    from cdp import Chrome, chrome_path
    if chrome_path() is None:
        pytest.skip("Chrome not installed")
    with Chrome(alarm=60) as c:
        c.goto(site["url"])
        c.js("localStorage.clear()")
        c.goto(site["url"])
        c.js("document.querySelector('[data-tab=hops]').click()")
        c.js("document.querySelector('.seg [data-repo=nanochat]').click()")
        n = len(md_lines("nanochat", "flow_hops_to_mark", "- [ ] required"))
        assert c.js("document.getElementById('hopprog').textContent") == f"nanochat 0 of {n} hops marked"
        c.key("ArrowDown", code="ArrowDown")
        c.key("r", code="KeyR")                      # hop 2 of nc-flo-01: required, cursor moves to hop 3
        c.key("o", code="KeyO")
        c.key("x", code="KeyX")                      # hop 4: excluded, shown struck through
        c.wait(f"document.getElementById('hopprog').textContent === 'nanochat 3 of {n} hops marked'")
        c.wait("document.getElementById('saved').textContent === 'Saved'")
        doc = json.loads((site["dir"] / "hops_nanochat.json").read_text())
        assert [h["mark"] for h in doc["questions"]["nc-flo-01"]["hops"][:5]] == [
            None, "required", "optional", "excluded", None]
        assert c.js("document.querySelectorAll('.hop.excluded').length") == 1
        assert c.js("document.querySelector('.hop.excluded [data-mark=excluded]').getAttribute('aria-pressed')") == "true"
        c.key("n", code="KeyN")
        assert c.js("document.querySelector('.fq.cur').dataset.q") == "nc-flo-02"

        c.js("document.querySelector('[data-tab=t5]').click()")
        assert "Don't look at Honeyguide's map" in c.js("document.getElementById('reminder').textContent")
        c.click_el("#addwhy")
        c.wait("document.querySelectorAll('#whylist .wq').length === 1")
        c.wait("document.activeElement && document.activeElement.matches('textarea.q')")
        c.type("Why does the model keep a separate KV cache per row?")
        c.wait("document.getElementById('saved').textContent === 'Saved'", timeout=5)
        doc = json.loads((site["dir"] / "whyhow_nanochat.json").read_text())
        assert [q["text"] for q in doc["questions"]] == ["Why does the model keep a separate KV cache per row?"]
        assert doc["questions"][0]["id"] == "nc-why-01" and doc["manifest_sha256"] == chores.manifest_sha()
        assert c.console_errors() == []


# ---------- the excluded mark, the refinements of 2026-11-16, the export ----------

def test_excluded_mark_round_trips_and_keeps_why_and_extras(tmp_path):
    a = chores.Answers(tmp_path)
    a.set_hop("nanochat", "nc-flo-04", 0, "excluded")
    path = tmp_path / "hops_nanochat.json"
    doc = json.loads(path.read_text())
    doc["provenance"] = "drafted, confirmed"
    doc["questions"]["nc-flo-04"]["hops"][0]["why"] = "before the call asked about"
    chores.write_json(path, doc)
    b = chores.Answers(tmp_path)
    assert b.hops["nanochat"]["nc-flo-04"][0] == "excluded"
    b.set_hop("nanochat", "nc-flo-04", 1, "required")                 # a page save keeps the why and the extras
    doc = json.loads(path.read_text())
    assert doc["provenance"] == "drafted, confirmed"
    assert doc["questions"]["nc-flo-04"]["hops"][0] == {
        "index": 0, "file": "nanochat/engine.py", "qual": "Engine.__init__", "line": 171, "mark": "excluded",
        "why": "before the call asked about"}
    s = chores.summarize(tmp_path)
    assert s["repos"]["nanochat"]["hops"]["by_mark"] == {"required": 1, "optional": 0, "excluded": 1}
    assert s["repos"]["nanochat"]["hops"]["marked"] == 2


def test_whyhow_keeps_relevant_original_source_and_policy(tmp_path):
    a = chores.Answers(tmp_path)
    q = a.add_whyhow("waku-agent")
    a.save_whyhow("waku-agent", [dict(q, text="Why?", rubric_must=list("abcdef"), relevant="waku/db.py",
                                      relevant_original="waku/")])
    path = tmp_path / "whyhow_waku-agent.json"
    doc = json.loads(path.read_text())
    assert doc["grading_policy"] == chores.GRADING_POLICY
    doc["source"] = "Han's message"
    chores.write_json(path, doc)
    b = chores.Answers(tmp_path)
    b.save_whyhow("waku-agent", b.whyhow["waku-agent"]["questions"])
    doc = json.loads(path.read_text())
    assert doc["source"] == "Han's message"
    assert doc["questions"][0]["relevant_original"] == "waku/" and len(doc["questions"][0]["rubric_must"]) == 6
    assert "relevant_original" not in b.add_whyhow("waku-agent")       # a new question has none
    assert chores.relevant_paths(" a.py; b/c.py ;") == ["a.py", "b/c.py"]


ANSWERS = json.loads((chores.ANSWERS / "whyhow_nanochat.json").read_text()) if (
    chores.ANSWERS / "whyhow_nanochat.json").exists() else None


@pytest.mark.skipif(ANSWERS is None, reason="no answers saved")
def test_the_refined_key():
    """The refinements Han accepted on 2026-11-16, as they stand in eval/human/answers/."""
    hops = json.loads((chores.ANSWERS / "hops_nanochat.json").read_text())
    h0 = hops["questions"]["nc-flo-04"]["hops"][0]
    assert (h0["qual"], h0["mark"]) == ("Engine.__init__", "excluded") and "before generate" in h0["why"]
    marks = [h["mark"] for r in REPOS for q in json.loads((chores.ANSWERS / f"hops_{r}.json").read_text())[
        "questions"].values() for h in q["hops"]]
    assert marks.count("excluded") == 1
    whys = {}
    for r in REPOS:
        doc = json.loads((chores.ANSWERS / f"whyhow_{r}.json").read_text())
        assert doc["grading_policy"] == chores.GRADING_POLICY and doc["refinement"].startswith("Refined 2026-11-16")
        assert all("grading_policy" not in q for q in doc["questions"])
        whys.update({q["id"]: q for q in doc["questions"]})
    assert whys["nc-why-07"]["rubric_must"][-1].startswith("Identify the roles of Engine.generate, KVCache.prefill")
    assert whys["wk-why-02"]["rubric_must"][-1].startswith("Identify the concrete agent loop")
    assert whys["wk-why-04"]["rubric_must"][-1].startswith("Distinguish the decision to retrieve memory")
    for q in whys.values():
        assert chores.RUBRIC_MIN <= len(q["rubric_must"]) <= chores.RUBRIC_MAX
        if q["repo"] == "waku-agent":                                   # exact files, Han's string kept
            assert q["relevant_original"] and not any(p.endswith("/") for p in chores.relevant_paths(q["relevant"]))


@pytest.mark.parametrize("repo", REPOS)
def test_relevant_files_exist_at_the_pin(repo):
    data = json.loads((QDIR / f"{repo}.json").read_text())
    clone = Path.home() / "Documents" / "GitHub" / "honeyguide-targets" / repo
    path = chores.ANSWERS / f"whyhow_{repo}.json"
    if not clone.exists() or not path.exists():
        pytest.skip("no local clone or no answers")
    tracked = set(subprocess.run(["git", "-C", str(clone), "ls-tree", "-r", "--name-only", data["commit"]],
                                 capture_output=True, text=True, check=True).stdout.split())
    for q in json.loads(path.read_text())["questions"]:
        for p in chores.relevant_paths(q["relevant"]):
            assert p in tracked, (q["id"], p)


def test_export_links_and_one_grading_policy():
    sys.path.insert(0, str(ROOT / "eval" / "human"))
    import export
    out = export.build()
    t5, t6a, t6b = out["t5_whyhow.json"], out["t6_flow_hops.json"], out["t6_callers.json"]
    assert t5["grading_policy"] == chores.GRADING_POLICY
    assert set(t6a["marks"]) == set(chores.MARKS)
    for r in REPOS:
        data = json.loads((QDIR / f"{r}.json").read_text())
        base = f"{data['url']}/blob/{data['commit']}/"
        for q in t5["repos"][r]["questions"]:
            assert "grading_policy" not in q
            assert [f["path"] for f in q["relevant_files"]] == chores.relevant_paths(q["relevant"])
            assert all(f["link"] == base + f["path"] for f in q["relevant_files"])
        for q in t6a["repos"][r]["questions"]:
            for h in q["hops"]:
                assert h["link"] == f"{base}{h['file']}#L{h['line']}" and h["count"] >= 1
        for q in t6b["repos"][r]["questions"]:
            for d in q["disputes"]:
                assert d["link"] == f"{base}{d['file']}#L{d['lines'][0]}"
