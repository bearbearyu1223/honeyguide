"""The map document's Overview topics, list and facts blocks, module facts; the readability check; the
draft-files workflow (map draft-dir, check, ingest) and its guard; --input on JSON commands. Old maps still validate.
"""

from __future__ import annotations

import copy
import json

import pytest
from test_contract_fixtures import World, a_map

from honeyguide.mapdoc import OVERVIEW_TOPICS, block_text, check_document, claim_refs, plain_text, span_ranges
from honeyguide.readability import check_readability, has_verb, prose_issues

# -- readability fixtures: short excerpts ---------------------------------------------------------------------------

# An Overview of a small sample project, written as full sentences (as a well-written map reads).
SAMPLE_PROSE = [
    ("purpose", "The tool turns a folder of Markdown notes into a small static website in three steps: a reader parses "
                "every note into a tree of headings and paragraphs, a linker resolves the links between notes into "
                "page addresses, and a writer renders each tree through one page template. The linker is the only "
                "part that looks at more than one note at a time; the writer can also emit a single combined page "
                "for printing."),
    ("purpose", "It is a **teaching example**, not a production generator. The sample notes are short pages about "
                "birds, written by hand, chosen so that every link either resolves or fails in an obvious way. The "
                "interesting output is a report of broken and orphaned links, and whether renamed notes are still "
                "found, rather than the pages themselves."),
    ("users", "Readers of the tutorial who want to rebuild its sample site, and whoever extends the generator with a "
              "new note format. The tone of the guide and the `examples/` folder are built around comparing a build "
              "with the published one; there is no server, no plugin system, no notion of a visitor editing a "
              "page."),
]
SAMPLE_ITEMS = [
    ("capabilities", "Parse every note once and cache its tree, then link and render the site as separate commands "
                     "against the same cache."),
    ("capabilities", "Check a built site against three controls (an empty folder, a folder with one note, a folder "
                     "with one broken link) plus renamed notes and duplicate titles."),
    ("entry-points", "`notesite` console script, resolved to `notesite.cli:main`. Six subcommands, each with its own "
                     "`cmd_*` function."),
    ("start-here", "`src/notesite/link.py`: one 120-line file. Seeing that every page goes through the same lookup "
                   "table removes most of the apparent complexity."),
    ("start-here", "`src/notesite/report.py`: the link report, which is the main point of the project."),
]

# The first real nanochat map (its saved map.json): telegraph style.
NANOCHAT_OVERVIEW = [
    "A minimal single-node LLM harness. --depth sets model size.",
    "speedrun.sh: tokenizer, d24 pretrain, SFT. RL is optional. Artifacts in NANOCHAT_BASE_DIR, per-stage "
    "checkpoints. Start at gpt.py, base_train.py.",
    "No autocast: bf16 on Ampere+, Linear casts weights. No DDP.",
]
NANOCHAT_MODULES = [
    "GPTConfig; meta init; rotary+QK norm; relu^2 MLP; value embeds; S = 1/4 context; resid/x0 mix; smear; backout; "
    "softcap 15; loss; AdamW/Muon groups; FLOPs; KV costs.",
    "3-phase step; fused AdamW; fused Muon; cautious WD; ZeRO-2; 1-GPU path.",
    "Val split; rank stride; BOS; best-fit, 35% cropped; one copy.",
]


def doc_of(overview_blocks, module_texts=()) -> dict:
    return {"title": "t", "sections": [
        {"id": "o", "kind": "overview", "title": "Overview", "blocks": overview_blocks},
        {"id": "m", "kind": "modules", "title": "Modules", "blocks": [
            {"id": f"m{i}", "type": "module", "path": f"f{i}.py", "spans": [{"text": t}]}
            for i, t in enumerate(module_texts)]}]}


def test_readability_passes_a_full_sentence_overview():
    blocks = [{"id": f"p{i}", "type": "text", "topic": t, "spans": [{"text": x}]} for i, (t, x) in enumerate(SAMPLE_PROSE)]
    blocks += [{"id": f"l{i}", "type": "list", "topic": t, "items": [{"spans": [{"text": x}]}]}
               for i, (t, x) in enumerate(SAMPLE_ITEMS)]
    errors, warnings = check_readability(doc_of(blocks), strict=False)
    assert errors == [] and warnings == [], warnings


def test_readability_fails_the_nanochat_telegraph_overview_and_modules():
    blocks = [{"id": f"o{i}", "type": "text", "spans": [{"text": t}]} for i, t in enumerate(NANOCHAT_OVERVIEW)]
    errors, warnings = check_readability(doc_of(blocks, NANOCHAT_MODULES), strict=False)
    joined = "\n".join(errors)
    assert "overview: 3 of 3 prose blocks" in joined and "modules: 3 of 3 prose blocks" in joined
    assert "(o0): telegraph style" in joined and "(o1): telegraph style" in joined and "(m1): telegraph style" in joined   # m0 has one kind; the section rule catches it
    kinds = "\n".join(warnings)
    for kind in ("short", "choppy", "semicolons", "verbless", "abbreviation"):
        assert f": {kind}:" in kinds, kind
    assert "SFT" in kinds and "DDP" in kinds and "bf16" in kinds


def test_overview_length_counts_the_prose_only():
    """The 250-450 word target counts the Overview's prose, as map check's overview_words does; facts rows still
    explain abbreviations but don't add to the length."""
    from honeyguide.cli import _draft_summary
    from honeyguide.readability import OVERVIEW_WORDS
    para = " ".join(["The trainer reads each shard and writes one checkpoint for every step."] * 30)
    blocks = [{"id": "b1", "type": "text", "topic": "purpose", "spans": [{"text": para}]},
              {"id": "b2", "type": "facts", "topic": "commands",
               "rows": [{"key": "run", "spans": [{"text": " ".join(["word"] * 200)}]}]}]
    doc = {"title": "t", "sections": [{"id": "o", "kind": "overview", "title": "Overview", "blocks": blocks}]}
    n = _draft_summary({"document": {**doc, "flows": []}, "claims": []}, [])["overview_words"]
    assert OVERVIEW_WORDS[0] <= n <= OVERVIEW_WORDS[1] and n + 200 > OVERVIEW_WORDS[1]
    _, warnings = check_readability(doc, strict=True)
    assert not [w for w in warnings if "overview: length" in w], warnings
    blocks[0]["spans"][0]["text"] = " ".join(["The trainer reads each shard and writes one checkpoint."] * 60)
    _, warnings = check_readability(doc, strict=True)
    assert [w for w in warnings if "overview: length" in w] == ["readability: overview: length: 540 words; aim for "
                                                                "250-450"]


def test_readability_rules_one_by_one():
    assert [k for k, _ in prose_issues("No DDP.")] == ["short", "verbless"]
    assert not has_verb("Val bpb, CORE") and has_verb("It reshuffles the shards") and has_verb("the cache is kept")
    assert [k for k, _ in prose_issues("Shards load lazily; each shard is memory-mapped once and never copied "
                                       "whole into memory, so startup stays fast.")] == []
    assert "semicolons" in [k for k, _ in prose_issues("ZeRO-2; fused AdamW; Muon; cautious decay for each weight")]
    # code in backticks is one word and never an abbreviation; a parenthesis explains a term
    assert prose_issues("The `GPT2_CFG` constant holds every setting that the training script reads at start-up.", abbrev_context="") == []
    ctx = "It runs supervised fine-tuning (SFT) after pretraining."
    assert prose_issues("SFT runs after pretraining, on the chat data mixture the repo ships.", abbrev_context=ctx) == []
    assert prose_issues("SFT runs after pretraining, on the chat data mixture the repo ships.",
                        abbrev_context="")[0][0] == "abbreviation"
    # list items: shorter is fine, but a bare label is not
    assert prose_issues("`train.py` is where training starts.", kind="item") == []
    assert [k for k, _ in prose_issues("`train.py`", kind="item")] == ["short"]


# -- the v2 contract ------------------------------------------------------------------------------------------------

def S(text, claim=None):
    return {"text": text, "claim": claim} if claim else {"text": text}


def v2_draft() -> dict:
    """``a_map`` with an Overview in topic groups (text, list, facts) and a module block with facts."""
    data = a_map()
    data["claims"] += [
        {"key": "nocli", "text": "There is no command-line interface", "evidence": "searched_not_found",
         "searched": ["argparse", "__main__"]},
        {"key": "entry", "text": "`cli.py`'s `main` is the only entry point", "evidence": "read_in_source",
         "anchors": [{"path": "cli.py", "anchor": "def main():"}]},
    ]
    para = [S("The toy engine wraps a model and "), S("yields three outputs for every prompt it is given", "gen"),
            S(", which makes it the smallest thing that still shows how a generator-based sampler works.")]
    t = lambda topic, bid, kind, **rest: {"id": bid, "type": kind, "topic": topic, **rest}  # noqa: E731
    data["document"]["sections"][0]["blocks"] = [
        t("purpose", "ov-purpose", "text", spans=para),
        t("users", "ov-users", "text", spans=[S("Anyone learning the engine reads it, because "),
                                              S("generators are lazy", "gk"),
                                              S(" and the engine shows that laziness in a dozen lines of code.")]),
        t("capabilities", "ov-can", "list", items=[{"spans": [S("The `sample` helper "), S("calls Engine.generate",
                                                                                              "call"),
                                                              S(" and collects every output into a list.")]}]),
        t("commands", "ov-cmd", "facts", rows=[{"key": "run", "spans": [S("There is no command-line interface",
                                                                          "nocli"), S("; import `cli.main`.")]}]),
        t("entry-points", "ov-entry", "list", items=[{"spans": [S("`cli.py`'s `main` is the only entry point",
                                                                  "entry"), S(", and it runs `sample` once.")]}]),
        t("components", "ov-parts", "facts", rows=[{"key": "engine.py", "spans": [S("The engine and `sample`.")]}]),
        t("start-here", "ov-start", "list", ordered=True,
          items=[{"spans": [S("Read `engine.py` first, because the whole repo is that one class.")]}]),
    ]
    data["document"]["sections"].insert(1, {"id": "modules", "kind": "modules", "title": "Modules", "blocks": [
        {"id": "m-engine", "type": "module", "files": ["engine.py"], "role": "the engine",
         "title": "engine.py: the generator behind sample",
         "spans": [S("The engine holds the model and nothing else. Its one method "),
                   S("yields three outputs", "gen"), S(", one per call to the model, so callers must consume it.")],
         "design": [S("Because "), S("generators are lazy", "gk"), S(", nothing runs until a caller iterates, which is "
                    "why `sample` wraps the call in `list` instead of returning the generator itself.")],
         "facts": [{"key": "responsibility", "spans": [S("Turning a prompt into outputs.")]},
                   {"key": "key_symbols", "spans": [S("`Engine.generate(tokens)` and `sample(prompt)`.")]},
                   {"key": "interfaces", "spans": [S("`Engine.generate(tokens)` returns a generator.")]},
                   {"key": "callers", "spans": [S("sample calls Engine.generate", "call")]},
                   {"key": "tests", "spans": [S("None in this repo.")]}]}]})
    data["document"]["coverage"] = {"deep": [{"area": "engine.py, cli.py", "why": "Two short files, read in full."}],
                                    "skipped": [{"area": "README.md", "why": "It repeats the docstrings."}]}
    return data


def test_v2_document_is_valid_strict_and_its_plain_text_has_every_segment(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    draft = v2_draft()
    errors, _ = check_document(draft["document"], strict=True)
    assert errors == []
    code, out = w.call("map", "validate", "--stdin", "--strict", data=draft)
    assert code == 0 and out["valid"], out
    assert out["readability"]["errors"] == []
    # every segment of a block is in the plain text, one newline apart; span ranges cover list and facts spans
    module = draft["document"]["sections"][1]["blocks"][0]
    assert block_text(module).count("\n") == 6 and "\nsample calls Engine.generate\n" in block_text(module)
    assert block_text(module).split("\n")[1].startswith("Because generators are lazy")   # design follows the summary
    text = plain_text(draft["document"])
    claimed = [(s, e, c) for s, e, c in span_ranges(draft["document"]) if c]
    assert {c for *_, c in claimed} == {"gen", "gk", "call", "nocli", "entry"}
    for s, e, c in claimed:
        assert text[s:e] in {x["text"] for x in draft["claims"]} | {"yields three outputs for every prompt it is given",
                                                                    "generators are lazy", "calls Engine.generate",
                                                                    "yields three outputs"}, (c, text[s:e])
    assert claim_refs(draft["document"]).count("call") == 3   # the list item, the module fact, the hop


def test_strict_needs_every_topic_in_order_and_module_facts():
    doc = v2_draft()["document"]
    blocks = doc["sections"][0]["blocks"]
    bad = copy.deepcopy(doc)
    bad["sections"][0]["blocks"] = [b for b in blocks if b["topic"] != "users"]
    bad["sections"][0]["blocks"][0], bad["sections"][0]["blocks"][1] = (bad["sections"][0]["blocks"][1],
                                                                        bad["sections"][0]["blocks"][0])
    del bad["sections"][1]["blocks"][0]["facts"]
    errors = "\n".join(check_document(bad, strict=True)[0])
    assert "missing topic(s) users" in errors and "comes after 'capabilities'" in errors
    assert "needs facts, starting with responsibility" in errors
    # not strict: missing topics and facts are still errors once topics are used? only order and coverage are
    loose = "\n".join(check_document(bad)[0])
    assert "missing topic(s) users" in loose and "needs facts" not in loose
    worse = copy.deepcopy(doc)
    worse["sections"][1]["blocks"][0]["facts"] = [{"key": "callers", "spans": [S("x")]},
                                                  {"key": "responsibility", "spans": [S("y")]},
                                                  {"key": "owner", "spans": [S("z")]}]
    worse["sections"][0]["blocks"][3]["items"] = [{"spans": [S("x")]}]
    worse["sections"][1]["blocks"][0]["topic"] = "purpose"
    errors = "\n".join(check_document(worse)[0])
    assert "responsibility must be the first row" in errors and "'owner' is not a module fact" in errors
    assert "items belong to a list block" in errors and "topic is for Overview blocks only" in errors
    assert set(OVERVIEW_TOPICS) == {b["topic"] for b in blocks}


def test_old_maps_still_validate_and_keep_their_revision(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    code, out = w.call("claims", "save", data=a_map())
    assert code == 0
    rev = out["revision"]
    code, out = w.call("map", "validate")
    assert code == 0 and out["valid"] and out["warnings"] == []
    assert "readability" in out and out["readability"]["errors"] == []
    assert w.store.load("map")["document"]["revision"] == rev
    # strict, an old map is not a v2 map
    code, out = w.call("map", "validate", "--strict")
    assert not out["valid"] and any("topic groups" in e for e in out["errors"])


def test_saved_telegraph_map_is_valid_but_reported(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    data = a_map()
    data["document"]["sections"][0]["blocks"] = [
        {"id": f"o{i}", "type": "text", "spans": [{"text": t}] + ([S(" x", "gen")] if i == 0 else [])}
        for i, t in enumerate(NANOCHAT_OVERVIEW)]
    data["claims"] = [c for c in data["claims"] if c["key"] != "gk"]
    code, out = w.call("claims", "save", data=data)
    assert code == 0, out
    code, out = w.call("map", "validate")
    assert out["valid"] and out["readability"]["errors"]
    code, out = w.call("map", "validate", "--stdin", "--strict", data=data)
    assert not out["valid"] and any("telegraph style" in e for e in out["errors"])


# -- --input, draft files, check, ingest, guard ----------------------------------------------------------------------

def test_map_validate_takes_input_without_stdin(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    f = tmp_path / "draft.json"
    f.write_text(json.dumps(v2_draft()))
    code, out = w.call("map", "validate", "--input", str(f), "--strict")
    assert code == 0 and out["valid"], out
    code, out = w.call("anchor", "resolve", "--input", str(tmp_path / "missing.json"))
    assert code == 1 and out["error"]["code"] == "bad_input"


def write_drafts(d, draft: dict) -> None:
    doc = draft["document"]
    by_kind = {s["kind"]: s for s in doc["sections"]}
    (d / "meta.json").write_text(json.dumps({"title": doc["title"], "coverage": doc["coverage"]}))
    (d / "overview.json").write_text(json.dumps(by_kind["overview"]))
    (d / "modules.json").write_text(json.dumps(by_kind["modules"]))
    (d / "flows.json").write_text(json.dumps({**by_kind["flows"], "flows": doc["flows"]}))
    (d / "claims-a.json").write_text(json.dumps(draft["claims"][:2]))
    (d / "claims-b.json").write_text(json.dumps({"claims": draft["claims"][2:]}))


def test_draft_dir_check_and_ingest(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    code, out = w.call("map", "draft-dir")
    d = tmp_path / "x"
    assert code == 0
    from pathlib import Path
    d = Path(out["dir"])
    assert d.is_dir() and d.parent.parent == w.store.dir and d.name == "map"
    write_drafts(d, v2_draft())
    code, out = w.call("map", "check", str(d))
    assert code == 0 and out["valid"], out
    assert out["claims"] == 5 and out["flows"] == 1 and out["files"][0] == "claims-a.json"
    assert out["overview_words"] > 50 and w.store.load("map")["document"] is None   # check saves nothing
    monkeypatch.setenv("HONEYGUIDE_NO_GH", "1")
    code, out = w.call("map", "ingest", str(d))
    assert code == 0 and out["revision"] and len(out["saved"]) == 5, out
    doc = w.store.load("map")["document"]
    # Ingest stores the repo card (git facts; GitHub counts off here)
    assert doc["repo"]["commits"] >= 1 and doc["repo"]["github"] is None and doc["repo"]["github_note"].startswith("GitHub counts not fetched")
    assert [s["kind"] for s in doc["sections"]] == ["overview", "modules", "flows"] and doc["flows"][0]["id"] == "p1"
    assert doc["sections"][0]["blocks"][3]["rows"][0]["spans"][0]["claim"].startswith("c_")
    code, out = w.call("map", "validate", "--strict")
    assert out["valid"], out
    # --fresh empties the drafts
    code, out = w.call("map", "draft-dir", "--fresh")
    assert list(d.glob("*.json")) == []


def test_ingest_refuses_bad_drafts_and_writes_nothing(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    from pathlib import Path
    d = Path(w.call("map", "draft-dir")[1]["dir"])
    draft = v2_draft()
    draft["document"]["sections"][0]["blocks"][0]["spans"] = [S(NANOCHAT_OVERVIEW[2]), S(" x", "gen")]
    write_drafts(d, draft)
    (d / "notes.json").write_text("{}")
    code, out = w.call("map", "ingest", str(d))
    assert code == 1 and "notes.json: not a draft file" in "\n".join(out["error"]["details"])
    (d / "notes.json").unlink()
    code, out = w.call("map", "ingest", str(d))
    assert code == 1 and out["error"]["code"] == "validation_failed"
    assert any("telegraph style" in x for x in out["error"]["details"])
    assert w.store.load("map")["document"] is None
    (d / "overview.json").write_text("{not json")
    code, out = w.call("map", "check", str(d))
    assert code == 1 and "overview.json: not JSON" in "\n".join(out["error"]["details"])


@pytest.mark.parametrize("where", ["repo", "home", "link", "sibling", "drafts-root", "agent-drafts"])
def test_guard_refuses_drafts_from_anywhere_else(tmp_path, monkeypatch, where):
    w = World(tmp_path, monkeypatch)
    from pathlib import Path
    d = Path(w.call("map", "draft-dir")[1]["dir"])
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    write_drafts(outside, v2_draft())
    if where == "repo":
        target = w.root
    elif where == "home":
        target = outside
    elif where == "link":      # a draft file that is a symlink out of the store
        write_drafts(d, v2_draft())
        (d / "claims-a.json").unlink()
        (d / "claims-a.json").symlink_to(outside / "claims-a.json")
        target = d
    elif where == "drafts-root":   # drafts/ itself, not drafts/map/
        target = d.parent
    elif where == "agent-drafts":  # another agent's scratch directory under drafts/
        target = Path(w.call("drafts", "dir", "--agent", "checker")[1]["dir"])
        write_drafts(target, v2_draft())
    else:                      # the store itself, outside drafts/
        target = w.store.dir
    for action in ("check", "ingest"):
        code, out = w.call("map", action, str(target))
        assert code == 1 and out["error"]["code"] == "forbidden", (action, out)
    assert w.store.load("map")["document"] is None


# -- component modules (files, title, related, design), coverage, the module count -------------------------

from honeyguide.gitio import sum_grep_counts  # noqa: E402
from honeyguide.mapdoc import check_module_count, normalize_document  # noqa: E402


def test_component_module_fields_are_checked():
    doc = v2_draft()["document"]
    mod = doc["sections"][1]["blocks"][0]
    bad = copy.deepcopy(doc)
    m = bad["sections"][1]["blocks"][0]
    m.update(files=["engine.py", "engine.py", "/etc/x"], path="cli.py", title="a\ntitle", related=["nowhere", "m-engine"])
    m["design"] = []
    bad["sections"][0]["blocks"][0]["files"] = ["x.py"]
    errors = "\n".join(check_document(bad)[0])
    for want in ("files has a path twice", "files[2]: must be a repo-relative path", "path must be files[0]",
                 "title must be a one-line string", "design: spans must be a non-empty list",
                 "related 'nowhere' is not a module block id", "related names the module itself",
                 "files belongs to a module block"):
        assert want in errors, want
    # path alone (a block saved before components existed) or files alone are both fine; saving fills path from files
    assert mod["files"] == ["engine.py"] and "path" not in mod
    assert normalize_document(copy.deepcopy(doc))["sections"][1]["blocks"][0]["path"] == "engine.py"
    mod["path"] = "engine.py"
    del mod["files"]
    assert check_document(doc)[0] == []
    del mod["path"]
    assert "needs files (or path)" in "\n".join(check_document(doc)[0])


def test_draft_rules_for_modules_and_coverage():
    doc = v2_draft()["document"]
    m = doc["sections"][1]["blocks"][0]
    del m["title"], m["design"]
    m["facts"] = m["facts"][:3]
    del doc["coverage"]
    errors = "\n".join(check_document(doc, strict=True)[0])
    assert "needs a title" in errors and "3 facts rows; a module needs at least 5" in errors
    assert "needs a design paragraph" in errors and "document: needs coverage" in errors
    assert check_document(doc)[0] == []    # none of it applies to a saved map
    # a debug row stands in for the design paragraph
    m["facts"].append({"key": "debug", "spans": [S("Print the generator to see that nothing ran yet.")]})
    m["facts"].append({"key": "errors", "spans": [S("None raised.")]})
    m["title"] = "engine.py: the generator"
    doc["coverage"] = {"deep": [{"area": "everything", "why": "tiny"}]}
    assert check_document(doc, strict=True)[0] == []
    for cov, want in (({}, "name at least one area"), ({"read": []}, "'read' is not one of"),
                      ({"skipped": [{"area": "x"}]}, "skipped[0]: needs area and why"), ([], "must be an object")):
        doc["coverage"] = cov
        assert want in "\n".join(check_document(doc)[0]), want


def test_module_count_suits_the_repo_size():
    doc = {"sections": [{"kind": "modules", "blocks": [{"type": "module", "id": f"m{i}"} for i in range(3)]}]}
    assert check_module_count(doc, 2999) == []
    assert "3 module block(s) for 3001 lines" in check_module_count(doc, 3001)[0]
    doc["sections"][0]["blocks"] *= 6   # 18
    assert "18 module blocks" in check_module_count(doc, 100)[0]
    doc["sections"][0]["blocks"] = doc["sections"][0]["blocks"][:6]
    assert check_module_count(doc, 50_000) == []
    assert sum_grep_counts("HEAD:a.py\x0012\nHEAD:b:c.py\x0030\n\n") == 42


def test_draft_module_files_must_exist_and_design_is_plain_text_and_readable(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    draft = v2_draft()
    draft["document"]["sections"][1]["blocks"][0]["files"] = ["engine.py", "gone.py"]
    code, out = w.call("map", "validate", "--stdin", "--strict", data=draft)
    assert not out["valid"] and any("file 'gone.py' is not in the repo" in e for e in out["errors"]), out
    draft = v2_draft()
    draft["document"]["sections"][1]["blocks"][0]["design"] = [S("No DDP. Lazy."), S(" x", "gk")]
    code, out = w.call("map", "validate", "--stdin", "--strict", data=draft)
    assert not out["valid"] and any("(m-engine).design: telegraph style" in e for e in out["errors"]), out
    # saved, the design paragraph is in the plain text right after the summary, and path is filled in
    code, out = w.call("claims", "save", data=v2_draft())
    assert code == 0, out
    doc = w.store.load("map")["document"]
    assert doc["sections"][1]["blocks"][0]["path"] == "engine.py" and doc["coverage"]["deep"][0]["area"]
    assert "the call.\nBecause generators are lazy" in plain_text(doc).replace("consume it.", "the call.")


def test_the_page_fixtures_v2_map_passes_the_draft_rules(tmp_path):
    from page_fixture import DOCUMENT_V2, MAP_CLAIMS_V2, build

    import honeyguide.claims as claims_mod
    from honeyguide.gitio import Repo
    info = build(tmp_path, "v2")
    out = claims_mod.validate_draft(Repo.open(info["repo"]), {"target": "map", "claims": MAP_CLAIMS_V2,
                                                              "document": DOCUMENT_V2}, strict=True)
    assert out["valid"] and out["warnings"] == [] and out["readability"]["warnings"] == [], out
    comp = DOCUMENT_V2["sections"][1]["blocks"][0]
    assert comp["files"] == ["train.py", "optim.py"] and comp["design"] and comp["related"]


def test_the_cartographer_brief_teaches_components():
    from pathlib import Path
    brief = (Path(__file__).resolve().parent.parent / "agents" / "cartographer.md").read_text()
    section = brief.split("### Modules: one block per component")[1].split("### Quality bar")[0]
    for want in ("**6-15 modules**", "`title`", "`design`", "`related`", "`files`", "**Bad**", "**Good**",
                 '"coverage"' if '"coverage"' in section else "`coverage`", '"deep"', '"skipped"'):
        assert want in section, want
    assert "important file" not in brief
