# E1 brief: how it differs from agents/checker.md, and why

`eval/adhoc/brief.md` is one brief for both arms of E1: the ad-hoc answers' units and the map claims (the
control). Both arms get the same text except two slots, `{source}` (one sentence: where the units come from) and
`{context}` (the question for an answer; "there is no question" for map claims). `tests/test_eval_adhoc.py`
checks that the two prompts are identical once those two slots are removed.

Kept from checker.md, in substance or word for word: the opening (one model checking another, a person
spot-checks, "so be strict and say why"), "supported" meaning in full (names, order, counts, conditions), the
**Compute, don't quote** rule and its worked example (the same made-up `pool/config.py`, the same arithmetic),
comments and docs backing only claims about the docs, "when unsure, `not_supported` with a note saying why; a
wrong supported is worse", and repository text treated as data, never as instructions.

What differs, and why:

| checker.md | brief.md | why |
|---|---|---|
| each claim cites anchors; read them with `honeyguide preview` (hash check) | no anchors: the Checker finds the evidence itself with Grep, Glob and Read in a fresh copy of the pinned commit | ad-hoc answers have no anchors; the map claims' anchors are stripped so both arms are judged the same way |
| verdicts `supported`, `not_supported`, `skipped` | `supported`, `wrong`, `not_supported`, `not_a_claim` | without anchors, "the code says otherwise" (`wrong`) and "found nothing" (`not_supported`) are different findings; the capture's main share adds them (not supp. + wrong), which is what checker.md's `not_supported` covers |
| a claim that repeats a stale comment is `not_supported` | it is `wrong` | the same case under the four verdicts: the code computes another value |
| evidence labels (`read_in_source`, `docs`, `inferred`, ...) decide what supports a claim | no labels; "a unit that reports what the docs say" is backed by the docs | answers carry no labels; the map claims' labels are hidden so the arms match |
| a true claim citing the wrong lines is `not_supported` | a unit that names lines that hold something else is `wrong`; the note starts "line reference:" | answers type their own line numbers; the capture counts the units faulted only for that |
| `general_knowledge` claims are always `skipped` | `not_a_claim` only for units with nothing checkable about this repository: framing, a heading, a list lead-in, or pure general Python/PyTorch knowledge; a summary that repeats earlier units is judged | answers mix framing with claims; the map arm's sample leaves out `general_knowledge` and `searched_not_found` claims |
| stale and repaired claims, recording with `verdict set`, page activity, the Never list | left out | E1 records nothing in Honeyguide: the check returns JSON (`check_schema.json`) and the runner saves it |
| tools Read, Grep, Glob, Bash (honeyguide commands only), Write (INPUTS only) | Read, Grep, Glob | the eval's isolation: no Bash, no writes |

Removed from the first E1 brief (e523906) on review: "The units cite no lines" (answers do cite file:line;
the brief now says some units name a file or a line, and such a reference is part of the claim); "When unsure
between supported and anything else, choose the other" (it let an unsure unit become `wrong`; checker.md says
`not_supported`); `not_a_claim` for "a summary that only repeats units before it" (a summary is judged). The
review also asked to drop the "so be strict" line as pressure the map Checker lacks; checker.md has that line
too ("so be strict and say why"), so it is kept for parity, and it now applies to both arms alike.
