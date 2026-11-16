# Agent contract (T7.1; memory and refresh: T7.5; map v2 and drafts: T7.13)

What the agents (Guide, Cartographer, Investigator, Tracer, Checker) and the map page call, and the records they
read and write. Built on the T7a foundation (`memory-and-anchors.md`); standard library only. Exact work is a
script: agents quote text, the script resolves lines, hashes, ids, links and timestamps.

## Calling convention

Every agent command reads **one JSON object** on stdin (or `--input FILE`; on `map validate`, `--input` implies
`--stdin`) and prints **one JSON object** on
stdout. `--repo PATH` (default `.`) picks the checkout; memory is `$HONEYGUIDE_HOME/<repo-id>/` as in T7a.

- Success: exit 0, `{"ok": true, ...result}`.
- Failure: exit 1, `{"ok": false, "error": {"code": ..., "message": ..., "details": [...]}}`. Nothing was
  written. Codes: `bad_input`, `not_found`, `invalid_transition`, `validation_failed` (`details` lists every
  problem, one string each, so an agent can fix all at once), `secret_refused`, `lock_timeout`, `git_error`,
  `store_error`, and `forbidden` (the server: host, token or origin check failed; `map check` / `map ingest`:
  a directory outside the drafts directory).

Every write is one read-modify-write under the store's lock (10 s, then `lock_timeout`), landing by atomic
rename, so a crash leaves each file old or new, never half-written. Most commands change one file. Three
change several in **one hold of the lock** (so nothing another writer saves in between is lost), one atomic
rename per file: `verdict set` (map, answers), `claims retire` (answers, map) and `refresh apply` (answers,
map, session). Each is safe to re-run after a crash between two renames: verdicts and retirements are
idempotent, and `refresh apply` writes the map (whose commit moving to the target marks it done) after the
answers, so a crash leaves the map behind HEAD and a re-run finishes the job.

Agents: `guide`, `cartographer`, `investigator`, `tracer`, `checker`.

## Claims as agents write them (drafts)

```json
{"key": "k1", "text": "Engine.generate yields one token per step",
 "evidence": "read_in_source",
 "anchors": [{"path": "nanochat/engine.py", "anchor": "def generate(self, tokens", "extent": "block"}]}
```

`anchors[]` items: `path`, `anchor` (quoted text, one or more lines), optional `end_anchor` or
`extent: "block"`. The script resolves each at the call's `commit` (default HEAD) into a full CodeAnchor:
committed content, never the working tree, so text only in uncommitted edits is `not_found`. `key`
is the draft's local name, used by spans and hops; the saved claim gets a `c_<12 hex>` id and keeps `key`.
Rules, all checked before anything is written:

- `general_knowledge`, `searched_not_found`: **no** anchors (`searched_not_found` may carry `searched`: a list of
  the queries tried). Every other label: at least one anchor, and every anchor must resolve uniquely
  (`not_found` / `ambiguous` / `no_file` are errors, with the candidates).
- No anchor may point at a secret: credential-looking paths (`.env*`, `*.pem`, `*.key`, `id_rsa*`, `.netrc`,
  `credentials*`, `secrets.*`, `.ssh/`, `.aws/`, keystores...) or lines that look like a private key or token
  (`-----BEGIN ... PRIVATE KEY`, `AKIA...`, `ghp_...`, `sk-...`, `xox?-...`). Code `secret_refused`.

## Commands (agents)

| command | input | output |
|---|---|---|
| `anchor resolve` | `{path, anchor, end_anchor?, extent?, commit?}` or `{anchors: [...], commit?}` | `{results: [{status, anchor?, candidates, message, links?}]}`; `links` = `{github?, github_title, vscode, cursor}` |
| `claims save` | `{target: "map", mode: "replace"\|"add", commit?, document?, claims: [draft], retire?: [{claim, reason}]}` | `{saved: [{key, id}], revision, retired: [id], warnings}` |
| `claims list` | `{scope?: "map"\|"answers"\|"all", responses?: [r_...], check?, freshness?, ids?}` | `{claims: [claim + response], count}` |
| `claims retire` | `{claim \| claims: [id], reason}` | `{retired: [id], already_retired: [id]}` |
| `map validate` | none (the saved map), or `--stdin` / `--input FILE` with a `claims save` input; `--strict` applies the draft rules | `{valid, errors: [...], warnings: [...], readability: {errors, warnings}}` |
| `map draft-dir` | none; `--fresh` empties it of `.json` drafts first | `{dir}`: `<memory>/drafts/map/`, created |
| `map check DIR` | the draft files in `DIR` (below) | `map validate --strict`'s result + `{files, claims, blocks, flows, overview_words}`; saves nothing |
| `map ingest DIR` | the draft files in `DIR` | the same check, then `claims save`'s result + `readability`; on any error, `validation_failed` and nothing written |
| `verdict set` | `{claim, verdict, note?, anchors?, commit?}` or `{verdicts: [...]}` | `{set: n, current_again: [id]}` |
| `inbox` | none | `{open: [question], investigating: [question]}` |
| `question show` | `{id}` | `{question, thread: [ancestors, oldest first], context}` (`context` = retrieval: map claims, earlier answers, shared notes) |
| `question claim` | `{id, agent}` | `{question}` (open -> investigating) |
| `question fail` | `{id, reason}` | `{question}` (-> failed) |
| `question release` | `{id}` | `{question}` (investigating -> open, after a crashed attempt) |
| `question reopen` | `{id}` | `{question}` (failed -> open; what the page's retry calls) |
| `answer record` | `{question, agent, spans \| text, claims: [draft], path?, commit?, generation?}` | `{response, question}` |
| `activity start` | `{agent, question?, status}` | `{entry}` |
| `activity update` | `{id, status}` | `{entry}` |
| `activity finish` | `{id, state: "done"\|"failed", status?}` | `{entry}` |
| `activity list` | none | `{working: [...], recent: [...]}` |
| `preview` | `{path, start, end, commit?, context?}` or `{claim, anchor?: index}` | `{path, commit, start, end, lines: [{n, text, cited}], links}` |
| `refresh apply` | `{to?: rev (default HEAD), base?: rev, note?}` | the `refresh-plan --json` object + `{applied, previous_commit, entry}` |
| `memory state` | none | the memory state below (what the page header shows) |
| `refresh-log add` | `{base, target, counts, note?}` | `{entry}` (a manual note; `refresh apply` logs itself) |

`verdict set`: `verdict` is `supported` / `not_supported` / `skipped`; a `general_knowledge` claim only takes
`skipped`. Stores `check`, `checked_at`, `check_note`. A `retired` claim takes no verdict. On a **stale**
claim (the re-check after a refresh): `supported` needs `anchors` (draft anchor specs, resolved at `commit`,
default HEAD, under the same rules as `claims save`: unique, no secrets), which replace the claim's anchors and
make it `current` (`candidates` dropped); `not_supported` takes no anchors and leaves it `stale`; `skipped` is
refused. Both set `rechecked_at`. `anchors` on a current claim are refused unless equal to its anchors (a
re-run after a crash). All items are checked before anything is written.

`claims list`: claims only, never notes or question text (what the Checker reads instead of `export`). Each row
is the claim's `id, key, text, evidence, anchors, check, check_note, checked_at, freshness, freshness_reason,
candidates, searched, rechecked_at, retired_at` (those present) plus `response` (null for a map claim).
`check` and `freshness` take one value or a list; `responses` implies answers.

`claims retire` (and `claims save`'s `retire`, mode `add` only, so a rewritten claim and the retirement of the
one it replaces land in one write): sets `freshness: "retired"`, `freshness_reason` = the reason,
`retired_at`. Retired claims stay in the store: the page shows them struck through, retrieval never returns
them, refresh skips them, and "not shown by any span" warnings ignore them. Unknown ids: `not_found`, nothing
written.

`refresh apply`: plans (as `refresh-plan`) and applies in one hold of the lock, from the claims as saved at
that moment. Unchanged and moved claims get anchors at the target and `freshness: "current"`; stale claims
keep the anchors that were checked, get `freshness: "stale"`, a `freshness_reason`, `candidates: [{path,
start, end, symbol, state, hash}]` and `check: "unchecked"` (a claim already stale whose candidates are
identical, same lines and hash, keeps the Checker's verdict); claims whose code is gone are `retired`. The
map's `commit` becomes the target. A refresh-log entry `{at, base: <previous map commit>, target, counts:
{unchanged, moved, stale, retired, unanchored}, uncovered: <n>, note}` is appended to the session.

`answer record` is the crash-safe record-the-answer: questions and responses live in one file
(`answers.json`), so appending the response and setting the question `answered` is one atomic write. A retry after
a crash either finds the question still open/investigating (nothing was saved; record again) or `answered`
(`invalid_transition`, with `details` naming the saved response); it can never save two answers.

Session commands (not JSON-in): `honeyguide serve [--port 8780]`, `honeyguide watch --follow`.

## Question lifecycle

States: `open` -> `investigating` -> `answered` | `failed`. Allowed moves:

| from | to |
|---|---|
| open | investigating (claim), answered (record), failed (fail) |
| investigating | answered (record), failed (fail), open (release) |
| failed | open (retry from the page; `reopens` += 1) |
| answered | none. A follow-up is a new question. |

Question record (in `answers.json`, extends T7a's): `id, kind: "question", text, anchor (DocumentAnchor | null),
author, created_at, parent_response, status, agent (who claimed it), claimed_at, answered_at, response,
failed_at, error, reopens`. A follow-up has `parent_response` and an anchor on `answer:<parent_response>`.
Records saved before T7 have no `status`; they read as `open` until answered.

## Map document

`map.json`'s `document` (opaque in T7a) is:

```json
{"title": "nanochat", "revision": "<12 hex>",
 "sections": [{"id": "overview", "kind": "overview", "title": "Overview",
               "blocks": [{"id": "b1", "type": "text",
                           "spans": [{"text": "Training runs in "},
                                     {"text": "one loop in base_train.py", "claim": "c_..."}]}]}],
 "flows": [path record, ...]}
```

- `section.kind`: `overview`, `modules`, `flows`, `other`. `block.type`: `text`, `module` (adds `path`, the
  file it describes), `flow` (adds `flow`, a path record id; its spans are the caption), and (T7.13) `list`
  (`items: [{spans}]`, optional `ordered: true`) and `facts` (`rows: [{key, label?, spans}]`, keys unique in the
  block, <= 40 chars; the page shows `label`, else the key). On `list` and `facts`, `spans` is an optional
  lead-in. Ids match `[a-z0-9][a-z0-9-]*`, unique per document.
- **Overview topics (T7.13)**: Overview blocks carry `topic`, one of `purpose`, `users`, `capabilities`,
  `commands`, `entry-points`, `components`, `start-here` (page headings: Purpose, Who it's for, What it can do,
  Commands, Entry points, Components, Start here). Once any Overview block has a topic, every one must; each
  topic's blocks are contiguous, in that order, and all seven are present (a topic the repo lacks is a block
  citing a `searched_not_found` claim). `topic` on a block outside the Overview is an error. An Overview with no
  topics at all is a pre-T7.13 map: valid, except under the draft rules. The page draws the module graph after
  the `components` group (after the first block in an old Overview).
- **Module facts (T7.13)**: a `module` block may carry `facts: [{key, label?, spans}]`, keys from
  `responsibility`, `key_files`, `key_symbols`, `interfaces`, `io`, `callers`, `dependencies`, `external`,
  `errors`, `tests`, `debug`, unique, `responsibility` first when present. With `facts`, the block's `spans`
  (its summary) are optional. The page shows the summary and the responsibility row, and folds the other rows
  under "More" (a module whose folded rows hold a discussion or note opens by itself).
- **Component modules (T7.13b)**: a `module` block may carry `files` (a non-empty list of repo-relative paths,
  each once; `path`, kept for older readers, must then be `files[0]` or left out, and saving fills it in),
  `title` (one line, <= 100 chars, `"<files>: <role in a few words>"`; the page's heading), `related` (ids of
  other module blocks, each once, not itself; every id must exist: an error even on a saved map) and `design`
  (spans: why the component is built this way, or the sharp edge met first; the segment right after the
  summary). `files`, `title`, `related` and `design` on any other block are errors. A block with neither
  `files` nor `path` is an error.
- **Coverage (T7.13b)**: `document.coverage` (from `meta.json`'s `coverage`) is `{deep?, scanned?, skipped?}`,
  each a list of `{area, why}` strings, at least one area in all. Not plain text and not in the revision; the
  page shows it as "What this map covers" at the end of the Modules section (of the Overview when there is none).
- **Draft rules** (`map check`, `map ingest`, `map validate --strict`): all seven topics; every `module` block
  has a `title`, a summary, at least 5 facts starting with `responsibility`, and a `design` paragraph or a
  `debug` row; the document has `coverage`; every module file exists at the map's commit (a tracked file or a
  directory holding one); a repo over 3,000 lines of source (`Repo.source_lines`: text files with code
  extensions, `gitio.SOURCE_GLOBS`) has 6-15 module blocks, and no repo more than 15; readability errors are
  errors. `map check` reports `modules`, the module count.
- Optional on a `module` block (T7.4): `role`, the file's one-line role (a string, one line, <= 80 chars; shown
  after the path in the Modules heading, as the subtitle of that file's lanes in flow diagrams, and in the module
  graph), and `entry: true` on the module that is the repo's entry point (the module graph tags it ENTRY POINT).
  Neither is part of the plain text, so neither moves annotation offsets.
- **Claims to text**: a span with `claim` is that claim's rendered text. In drafts, `claim` is the draft `key`; save
  rewrites it to the id. A claim may back several spans; a claim no span shows is a warning.
- **Plain text** (what DocumentAnchor offsets index): section title, blank line, then each block's text,
  blocks separated by a blank line, sections separated by a blank line (`mapdoc.plain_text`). A block's text is
  its segments joined by one newline: its own `spans` (when present), a module's `design` (when present,
  T7.13b), then each `items[]` entry, then each
  `rows[]` (or a module's `facts[]`) entry, each segment its spans joined (`mapdoc.block_segments`). Topic
  headings and facts labels are not plain text. A pre-T7.13 block has one segment, so its text and the
  document's revision are unchanged.
  `revision` = first 12 hex of sha256 of the plain text plus the flows' JSON, set by the script; annotations on
  the map re-anchor when it changes.
- Answers use the same `spans` (or plain `text`); `answer:<id>` plain text is the spans joined.

## Readability (T7.13)

`map validate` reports `readability: {errors, warnings}` for the Overview and Modules (`readability.py`). Checked
prose: text blocks, module summaries and module design paragraphs ("paragraphs"; a design paragraph is judged
as its own block) and list items; flow captions, module titles and facts rows are not checked. Backtick code counts as one word and is never parsed.

| kind | warns when |
|---|---|
| `short` | a paragraph under 12 words; a list item under 5 |
| `choppy` | a paragraph of 2+ sentences averaging under 8 words |
| `semicolons` | 3+ `;`-separated fragments averaging under 6 words (or 2 averaging under 3) |
| `verbless` | a sentence of 2+ words with no verb (a list item: no verb anywhere in it) |
| `abbreviation` | Overview only: an abbreviation or short code word (`SFT`, `bf16`, `d24`) outside backticks, not in a list of common ones (`API`, `GPU`, `LLM`, `GPT`, ...), and not next to a parenthesis anywhere in the Overview (`supervised fine-tuning (SFT)`) |
| `length` | draft rules only: Overview prose outside 250-450 words; a module summary (not its design paragraph) outside 2-4 sentences |

**Errors**: a block with 2+ distinct kinds (telegraph style), or a section where 40% or more of the prose blocks,
and at least 3, have a kind other than `abbreviation`. Errors make a draft invalid; on a saved map they are
only reported (`valid` stays structural, so maps saved before T7.13 still validate).

## Draft files (T7.13)

The Cartographer writes the map as files with the Write tool, in `map draft-dir`'s directory
(`$HONEYGUIDE_HOME/<repo-id>/drafts/map/`), so the map never passes through a shell command line:

| file | holds |
|---|---|
| `meta.json` | `{title, coverage, commit?, mode?: "replace" (default) \| "add", retire?: [{claim, reason}]}`; `coverage` becomes `document.coverage` |
| `overview.json`, `modules.json`, `flows.json` | one section object each; `flows.json` also holds the path records as `flows: [...]` |
| `section-<name>.json` | any other section, in name order after flows |
| `claims.json`, `claims-<name>.json` | a list of claim drafts (or `{claims: [...]}`), merged in name order |

`overview.json`, `meta.json` and at least one claims file are required; any other `.json` file is an error
(non-JSON files are ignored). The files assemble into one `claims save` input. `map check` and `map ingest` read
only directories inside `<memory>/drafts/` (`guard.draft_dir_problem`): the repo, another path in the memory
store, or a draft file that is a symlink out of it is `forbidden`. In mode `add` the document may cite claims
already saved.

## Tracer path record

One per flow (in `document.flows`) or per Tracer answer (`response.path`):

```json
{"id": "p1", "title": "What happens when you call generate()",
 "lanes": [{"id": "engine", "label": "engine.py · Engine", "path": "nanochat/engine.py"}],
 "loops": [{"id": "tok", "label": "per new token"}],
 "hops": [{"from": "cli", "to": "engine", "call": "Engine.generate(tokens)", "returns": "Iterator[int]",
           "data": "list[int] -> Tensor[1, T]", "label": "starts decoding", "loop": "tok",
           "trace": "seen", "claim": "k3"}]}
```

Hops are in call order. `from`/`to` name lanes; `loop` (optional) names a loop frame; `trace` is `seen` (in the
runtime trace), `unseen` (read or inferred only), or `blind_spot` (where the trace can't see, e.g. C++ backward).
`claim` is required: every hop is a claim and obeys the claim rules, so it is anchor-cited or labelled. `returns`,
`data`, `label` and (T7.4) `note` are optional strings; `note` says what a blind spot hides or why an unseen hop is
inferred ("autograd runs in C++, so the trace sees this call but not its walk back"). Loops with no hop are a
warning.

How the page draws a path (T7.4: the Steps rail and the swimlane diagram, from the same record):
- Line style (Han's v3.1 choice 1): **dotted** = `blind_spot`; **solid** = `seen`, or `unseen` whose claim is read in
  source / asserted by a test / seen at runtime (the evidence shape says which); **dashed** = everything else
  (inferred: neither read nor seen). Dashed and dotted hops carry a note under the arrow (`note`, else `label`).
- Lanes: in order of first use in the hops; header = the lane's `label`, subtitle = the `role` of the module block
  whose `files` (or `path`) include the lane's `path` (T7.13b: without a `role`, the part of its `title` after
  ": "). The flow starts in the first hop's `from` lane (a start dot); there is no
  separate entry hop.
- Data: `returns` + `data` show as one pill, `[returns, data]` (`["returns", returns]` or `["data", data]` when only
  one is given). It goes back to whoever makes the next hop (a return arrow) or, when that is the callee's own lane,
  stays on that lane as a pill.
- Evidence shape: the hop claim's, withheld while the claim is stale, retired or (in the panel) unchecked.
- Module graph: calls between two lanes with different `path`s, across `document.flows`; lanes without a `path`
  (libraries) are left out. Boxes stay files; each file of a component leads to that component's module.

## Activity log (avatars)

`activity.json`: `{schema: "honeyguide/activity", version: 1, entries: [...]}`; entry = `{id: "a_<12 hex>",
agent, question (id | null), status (one line, <= 200 chars), state: "working"|"done"|"failed", started_at,
updated_at, ended_at}`. The page shows `working` entries as animated avatars beside their thread (map-wide when
`question` is null) and recently ended ones for 10 minutes. Ended entries beyond the newest 200 are dropped.

## Session state

`session.json`: `{schema: "honeyguide/session", version: 1, last_visit, previous_visit, refresh_log: [{at, base,
target, counts, uncovered, note}]}`. The page posts a visit on load.

## Memory state (the page header, T7.5)

`memory state` (and `status --json`'s `memory_state`; the page server should return it as `memory` in `GET
/api/state`):

| field | meaning |
|---|---|
| `state` | `empty` (nothing saved), `behind` (map commit is not HEAD: refresh not applied), `refreshing` (some stale claim still has `check: "unchecked"`), `up_to_date` |
| `headline` | the header text: `Not mapped yet`, `Map at <sha> · HEAD is <sha>: refresh pending`, `Refreshing · N claims being re-checked` (`1 claim`), `Up to date at <sha>` (12 hex) |
| `head`, `map_commit`, `dirty` | HEAD, the map's commit, `{tracked, untracked}` uncommitted counts |
| `freshness` | `{current, stale, retired}` claim counts, map and answers |
| `awaiting_recheck` | stale claims the Checker hasn't re-checked (the N in "Refreshing") |
| `stale_not_supported` | stale claims the Checker found no longer hold (flagged; the Cartographer rewrites map ones) |
| `previous_visit`, `last_visit` | from the session |
| `rechecked_since_visit` | claims with `rechecked_at > previous_visit`: "N claims re-checked since your last visit" |
| `checked_since_visit` | claims with any verdict since `previous_visit` (what `rechecked_since_visit` counted before T7.5) |
| `last_refresh` | the newest refresh-log entry, or null |

Page rules: a claim with `freshness: "stale"` loses its evidence mark and check mark and is shown as stale (with
its `freshness_reason`; a quiet flag too when `check` is `not_supported`); `retired` claims are shown struck
through; neither is ever shown as current. The header never says "Up to date" while `state` is
`refreshing` or `behind`.

## Page server

`honeyguide serve` binds `127.0.0.1` only. It refuses any request whose `Host` is not `127.0.0.1:<port>` or
`localhost:<port>` (DNS rebinding), and every `/api/` request must carry `X-Honeyguide-Token` (embedded in the
served page; stored `0600` in the memory dir, kept across restarts). POSTs also need `Content-Type:
application/json` and, when an `Origin` header is sent, the same origin. The page never starts Claude: posts
land in the inbox and the session's `watch` wakes the Guide.

| method, path | body / query | result |
|---|---|---|
| GET `/` | | the map page (T7.3), with `/page.css`, `/page.js`, `/boot.js`, `/diagrams.js` (T7.4), `/favicon.svg` |
| GET `/api/state` | | repo id, HEAD, map commit, counts, `previous_visit`, `rechecked_since_visit` (legacy: counts any verdict since the visit; the header uses `memory`'s), refresh log; plus `memory` (the memory state above, added in T7.4; the page header shows it) |
| GET `/api/map` | | the map layer |
| GET `/api/threads` | | questions (with status) and responses |
| GET `/api/notes` | | notes |
| GET `/api/activity` | | `{working, recent}` |
| GET `/api/preview` | `?path&start&end&commit` or `?claim&anchor` | as `preview` |
| POST `/api/question` | `{text, anchor?}` | `{question}` (open) |
| POST `/api/follow-up` | `{text, parent_response, anchor}` | `{question}` |
| POST `/api/note` | `{text, anchor?, share_with_agents?, from_response?}` | `{note}` |
| POST `/api/question/retry` | `{id}` | `{question}` (failed -> open) |
| POST `/api/visit` | `{}` | `{previous_visit, last_visit}` |

Page anchors are DocumentAnchors as the page computes them (`doc`, `revision`, `quote`, `start`, `end`); the
server checks the quote against the current plain text and fills in `context` itself.

## Watch

`honeyguide watch --follow` polls `answers.json` (default every 1 s) and prints one line per question that
becomes `open`: `<question id> <question|follow-up> <text, one line, <= 120 chars>`. On start it prints every
question already open (so nothing posted before the watcher started is missed), then only new ones; a question
re-opened from `failed` prints again. Without `--follow` it exits 0 after the first batch (exit 3 on
`--timeout`). It never writes.
