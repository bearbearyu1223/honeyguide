"""A readability check for the map's prose: catches telegraph style, the failure of the first real maps
("A minimal single-node LLM harness. --depth sets model size.", "GPTConfig; meta init; rotary+QK norm; ...").

Pure functions over plain text; no NLP library. The heuristics are deliberately simple and tuned on two kinds of text
(tests/test_mapdoc.py): an overview written in full sentences must pass, the telegraph-style overview of an early
nanochat map must fail.

What is checked (``prose`` = a text block, a module's summary or design paragraph, or a list item, in the
Overview and Modules; flow captions, module titles and facts rows are terse by design and not checked):

- ``short``: a paragraph (text block or module summary) under ``MIN_WORDS`` words; a list item under
  ``MIN_ITEM_WORDS``.
- ``choppy``: a paragraph of two or more sentences averaging under ``MIN_AVG`` words.
- ``semicolons``: ``;``-separated fragments averaging under ``MIN_SEMI_AVG`` words (a noun list, not prose).
- ``verbless``: a sentence of two or more words with no verb (``No DDP.``). In a list item, only when the whole
  item has none.
- ``abbreviation`` (Overview only): an abbreviation or short code word (``SFT``, ``bf16``, ``d24``) outside
  backticks, not in ``COMMON`` and not explained by a parenthesis anywhere in the Overview (``supervised
  fine-tuning (SFT)``).

Each issue is a warning. A block with ``ERROR_KINDS`` or more distinct kinds is an error, and so is a section where
at least ``ERROR_SHARE`` of the prose blocks (and at least ``ERROR_MIN_BLOCKS`` of them) have an issue other than
``abbreviation``: the whole section is telegraphic. Backtick code counts as one word and is never parsed.
"""

from __future__ import annotations

import re
from typing import Iterable

MIN_WORDS = 12
MIN_ITEM_WORDS = 5
MIN_AVG = 8.0
MIN_SEMI_AVG = 6.0
ERROR_KINDS = 2
ERROR_SHARE = 0.4
ERROR_MIN_BLOCKS = 3
OVERVIEW_WORDS = (250, 450)   # the brief's target length; outside it is a warning
SUMMARY_SENTENCES = (2, 4)    # a module summary's target; outside it is a warning

# Abbreviations an engineer reads without help.
COMMON = {
    "AI", "API", "APIs", "ASCII", "CI", "CLI", "CPU", "CPUs", "CSS", "CSV", "CUDA", "DNS", "GPU", "GPUs", "HTML",
    "HTTP", "HTTPS", "ID", "IDs", "IO", "JSON", "JSONL", "JS", "LLM", "LLMs", "MIT", "ML", "OS", "PDF", "PNG", "PR",
    "PRs", "RAM", "README", "REST", "SDK", "SQL", "SSH", "SVG", "TCP", "TOML", "UI", "URL", "URLs", "UTF", "UTF-8",
    "VRAM", "XML", "YAML", "MLP", "LoRA", "MPS", "TPU", "TPUs", "OK", "US", "UK", "PyTorch", "NumPy", "macOS",
    "iOS", "GitHub", "OAuth", "JWT", "TLS", "SSL", "UUID", "GB", "MB", "KB", "TB", "MiB", "GiB", "FAQ", "PyPI",
    "RNG", "NaN", "NaNs", "II", "III", "IV", "GPT", "GPTs", "BERT", "A100", "H100", "H200", "B200", "V100", "T4",
}

VERBS = set("""
accept access accumulate act add adjust allocate allow append apply ask assemble assert assign attach average avoid
be become begin bind block boot break bring build buffer cache calculate call can cancel carry cast catch change check
choose clean clear clip close collect combine come commit compare compile complete compute configure connect consume
contain continue control convert copy count cover crash create cut decay decide decode define delete depend describe
detect differ disable do download drive drop dump emit enable encode end ensure enter evaluate exist exit expect
explain export expose extend extract fail fall feed fetch fill filter find finish fit fix flag flatten flow follow
force fork format freeze gather generate get give go grow guard handle hash have help hide hold hook ignore implement
import include increase index infer inherit initialise initialize inject insert inspect install interleave invoke
is join keep kill know land launch lead learn leave let lift limit link list live load lock log look lose make map
mark match matter mean measure merge mix mock move need normalise normalize note notice open order output own pack
pad parse pass patch pause persist pick pin place plan play point poll post precompute predict prefer prepare
preserve pretrain print process produce project prompt protect provide pull push put query queue raise rank reach
read rebuild receive record reduce refer refresh refuse register reject release reload remove render repeat replace
report request require reset reshape resize resolve respond restart restore resume retry return reuse rewrite rotate
round route run sample save scale scan schedule score search seed select send separate serve set shape share shift
show shard shrink shuffle sit skip slice sort spawn speed split stack start stay step stop store stream strip
submit subclass support swap switch sync take talk teach tell test throw tie time tokenize touch trace track train
transform translate treat trigger trim try tune turn unpack update upload use validate verify wait walk want warm
watch wire work wrap write yield wait worry fuse decorate dispatch measure need sit see seem say mirror
""".split())
IRREGULAR = set("""
am are was were been being has had does did done doing goes went gone made making ran runs running took taken
gave given got gotten kept left led lost meant met paid put read said saw seen sent set shown sat sold split spent
stood told thought understood wrote written built bound brought caught chose chosen drew drawn fed fell felt found
fit forgot froze grew grown held hid hit hurt knew known laid let lay lit rose rode shook shot shut sang sank slid
spoke stuck struck swept swung threw thrown wore won wound
can could may might must shall should will would cannot isn't aren't wasn't weren't doesn't don't didn't hasn't
haven't won't can't couldn't shouldn't wouldn't it's that's there's here's what's
""".split())

CODE = re.compile(r"`[^`\n]+`")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'+./\-]*")
SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9`\"'(\[\-])")
ABBREV = re.compile(r"^(?:[A-Z][A-Z0-9]{1,6}s?|[a-z]{1,3}[0-9]{1,3}|[A-Z]{2,}[a-z]?[0-9]+)$")
NOT_ABBREV_AFTER = re.compile(r"[a-z]{2,}")


def _plain(text: str) -> str:
    """Backtick code becomes one placeholder word; whitespace is collapsed."""
    return " ".join(CODE.sub(" CODE ", text).split())


def words(text: str) -> list[str]:
    return WORD.findall(_plain(text))


def sentences(text: str) -> list[str]:
    """Sentences of ``text``: split after ``.!?`` before a capital, digit, quote or backtick."""
    flat = " ".join(CODE.sub(lambda m: m.group(0).replace(".", "․"), text).split())  # no splits inside code
    return [s.replace("․", ".") for s in SENTENCE_END.split(flat) if s.strip()]


def is_verb(word: str) -> bool:
    w = word.lower().strip("'.").removeprefix("re-")
    if w in IRREGULAR or w in VERBS:
        return True
    w = w.split("-")[-1] if "-" in w else w
    if w in VERBS or w in IRREGULAR:
        return True
    for suffix, stems in (("ies", ("y",)), ("es", ("", "e")), ("s", ("",)), ("ied", ("y",)), ("ed", ("", "e")),
                          ("d", ("",)), ("ing", ("", "e"))):
        if w.endswith(suffix) and len(w) > len(suffix) + 1:
            base = w[: -len(suffix)]
            if any(base + s in VERBS for s in stems):
                return True
            if suffix in ("ed", "ing") and len(base) > 2 and base[-1] == base[-2] and base[:-1] in VERBS:
                return True  # stepped, running
    # unknown regular forms: a past participle or gerund of a verb not in the list
    return len(w) > 5 and (w.endswith("ed") or w.endswith("ing")) and not w.endswith(("need", "speed", "seed"))


def has_verb(text: str) -> bool:
    return any(is_verb(w) for w in words(text) if w != "CODE")


def abbreviations(text: str) -> list[str]:
    """Abbreviation-like words outside backticks, not in ``COMMON``."""
    out = []
    for w in words(text):
        w = w.rstrip(".,:;")
        core = w.split("-")[0] if "-" in w and w.split("-")[0] else w
        for token in {w, core}:
            if token != "CODE" and token not in COMMON and ABBREV.match(token) and not token.isdigit():
                out.append(token)
                break
    return list(dict.fromkeys(out))


def explained(token: str, context: str) -> bool:
    """``token`` is spelled out next to a parenthesis somewhere in ``context``: ``X (expansion)`` or ``(X)``."""
    t = re.escape(token)
    return bool(re.search(rf"(?<![\w-]){t}(?![\w-])\s*\(", context) or re.search(rf"\(\s*{t}\s*[),]", context))


def prose_issues(text: str, kind: str = "paragraph", abbrev_context: str | None = None) -> list[tuple[str, str]]:
    """``(kind, message)`` issues for one piece of prose. ``kind``: ``paragraph`` or ``item``.

    ``abbrev_context`` (the whole Overview's text) turns the abbreviation check on.
    """
    issues: list[tuple[str, str]] = []
    n = len(words(text))
    if kind == "paragraph" and n < MIN_WORDS:
        issues.append(("short", f"{n} words; a paragraph needs at least {MIN_WORDS} (write sentences, not labels)"))
    if kind == "item" and n < MIN_ITEM_WORDS:
        issues.append(("short", f"{n} words; a list item needs at least {MIN_ITEM_WORDS} (say what and why)"))
    sents = sentences(text)
    if kind == "paragraph" and len(sents) >= 2:
        avg = sum(len(words(s)) for s in sents) / len(sents)
        if avg < MIN_AVG:
            issues.append(("choppy", f"{len(sents)} sentences averaging {avg:.1f} words (under {MIN_AVG:g}): "
                                     "join the fragments into sentences that explain"))
    plain = _plain(text)
    if plain.count(";") >= 1:
        parts = [p for p in re.split(r"[;]", plain) if p.strip()]
        avg = sum(len(WORD.findall(p)) for p in parts) / max(1, len(parts))
        if len(parts) >= 3 and avg < MIN_SEMI_AVG or len(parts) == 2 and avg < MIN_SEMI_AVG / 2:
            issues.append(("semicolons", f"{len(parts)} ';'-separated fragments averaging {avg:.1f} words: "
                                         "a list of labels, not prose"))
    if kind == "item":
        if n >= 2 and not has_verb(text):
            issues.append(("verbless", "no verb: say what it does or why it matters"))
    else:
        bare = [s for s in sents if len(words(s)) >= 2 and not has_verb(s)]
        if bare:
            issues.append(("verbless", "no verb in " + "; ".join(f"“{_clip(s)}”" for s in bare[:3])))
    if abbrev_context is not None:
        unexplained = [a for a in abbreviations(text) if not explained(a, abbrev_context)]
        if unexplained:
            issues.append(("abbreviation", "unexplained: " + ", ".join(unexplained[:6])
                           + " (spell it out once, e.g. 'supervised fine-tuning (SFT)', or quote code in backticks)"))
    return issues


def _clip(s: str, n: int = 50) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _text(spans: Iterable[dict]) -> str:
    return "".join(s.get("text", "") for s in spans)


def prose_pieces(document: dict) -> list[tuple[str, str, str, str]]:
    """``(section_kind, where, kind, text)`` for every checked piece of prose in a map document."""
    out = []
    for s, section in enumerate(document.get("sections") or []):
        kind = section.get("kind") if isinstance(section, dict) else None
        if kind not in ("overview", "modules"):
            continue
        for b, block in enumerate(section.get("blocks") or []):
            if not isinstance(block, dict):
                continue
            at = f"sections[{s}].blocks[{b}] ({block.get('id')})"
            if block.get("type") in ("text", "module") and block.get("spans"):
                out.append((kind, at, "paragraph", _text(block["spans"])))
            if block.get("type") == "module" and block.get("design"):
                out.append((kind, f"{at}.design", "paragraph", _text(block["design"])))
            elif block.get("type") == "list":
                for i, item in enumerate(block.get("items") or []):
                    if isinstance(item, dict):
                        out.append((kind, f"{at}.items[{i}]", "item", _text(item.get("spans") or [])))
    return out


def check_readability(document: dict, strict: bool = True) -> tuple[list[str], list[str]]:
    """``(errors, warnings)`` for a map document's Overview and Modules prose.

    ``strict`` adds the length targets (Overview words, module summary sentences) as warnings.
    """
    if not isinstance(document, dict):
        return [], []
    pieces = [t for k, _, _, t in prose_pieces(document) if k == "overview"]
    prose = " ".join(pieces)   # the length target counts the prose alone, as map check's overview_words does
    overview = "\n".join(pieces)   # the abbreviation context: the prose plus the facts rows below
    for section in document.get("sections") or []:
        if isinstance(section, dict) and section.get("kind") == "overview":   # facts rows can explain too
            for block in section.get("blocks") or []:
                for row in (block.get("rows") or []) if isinstance(block, dict) else []:
                    if isinstance(row, dict):
                        overview += "\n" + _text(row.get("spans") or [])
    errors: list[str] = []
    warnings: list[str] = []
    by_block: dict[str, set[str]] = {}
    per_section: dict[str, set[str]] = {"overview": set(), "modules": set()}
    flagged: dict[str, set[str]] = {"overview": set(), "modules": set()}
    for kind, where, piece, text in prose_pieces(document):
        block = where.split(".items[")[0]
        per_section[kind].add(block)
        issues = prose_issues(text, piece, overview if kind == "overview" else None)
        for name, message in issues:
            warnings.append(f"readability: {where}: {name}: {message}")
            by_block.setdefault(block, set()).add(name)
            if name != "abbreviation":   # an unexplained term alone doesn't make a section telegraphic
                flagged[kind].add(block)
        if strict and kind == "modules" and piece == "paragraph" and not where.endswith(".design"):
            n = len(sentences(text))
            lo, hi = SUMMARY_SENTENCES
            if not lo <= n <= hi:
                warnings.append(f"readability: {where}: length: the summary has {n} sentence(s); aim for {lo}-{hi}")
    for block, kinds in by_block.items():
        if len(kinds) >= ERROR_KINDS:
            errors.append(f"readability: {block}: telegraph style ({', '.join(sorted(kinds))}); rewrite it as "
                          "full sentences that explain")
    for kind in ("overview", "modules"):
        total, bad = len(per_section[kind]), len(flagged[kind])
        if total and bad >= ERROR_MIN_BLOCKS and bad / total >= ERROR_SHARE:
            errors.append(f"readability: {kind}: {bad} of {total} prose blocks have readability warnings "
                          f"(the limit is under {ERROR_SHARE:.0%}); the section reads as notes, not prose")
    if strict and prose:
        n = len(words(prose))
        lo, hi = OVERVIEW_WORDS
        if not lo <= n <= hi:
            warnings.append(f"readability: overview: length: {n} words; aim for {lo}-{hi}")
    return errors, warnings
