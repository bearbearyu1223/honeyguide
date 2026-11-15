# Agent contract (T7.1)

What the agents (Guide, Cartographer, Investigator, Tracer, Checker) and the map page call, and the records they
read and write. Built on the T7a foundation (`memory-and-anchors.md`); standard library only. Exact work is a
script: agents quote text, the script resolves lines, hashes, ids, links and timestamps.

## Calling convention

Every agent command reads **one JSON object** on stdin (or `--input FILE`) and prints **one JSON object** on
stdout. `--repo PATH` (default `.`) picks the checkout; memory is `$HONEYGUIDE_HOME/<repo-id>/` as in T7a.

- Success: exit 0, `{"ok": true, ...result}`.
- Failure: exit 1, `{"ok": false, "error": {"code": ..., "message": ..., "details": [...]}}`. Nothing was
  written. Codes: `bad_input`, `not_found`, `invalid_transition`, `validation_failed` (`details` lists every
  problem, one string each, so an agent can fix all at once), `secret_refused`, `lock_timeout`, `git_error`,
  `store_error`, and `forbidden` (server only:
  host, token or origin check failed).

Every write is one read-modify-write of one file under the store's lock (10 s, then `lock_timeout`), landing by
atomic rename, so a crash leaves each file old or new, never half-written. Every command changes one file,
except `verdict set` (map and answers, one write each; verdicts are idempotent, so rerunning it after a crash
finishes the job).

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
| `claims save` | `{target: "map", mode: "replace"\|"add", commit?, document?, claims: [draft]}` | `{saved: [{key, id}], revision}` |
| `map validate` | none (the saved map), or `--stdin` with a `claims save` input | `{valid, errors: [...], warnings: [...]}` |
| `verdict set` | `{claim, verdict, note?}` or `{verdicts: [...]}` | `{set: n}` |
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
| `refresh-log add` | `{base, target, counts, note?}` | `{entry}` |

`verdict set`: `verdict` is `supported` / `not_supported` / `skipped`; a `general_knowledge` claim only takes
`skipped`. Stores `check`, `checked_at`, `check_note`. Freshness is not touched here (T7.5).

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
  file it describes), `flow` (adds `flow`, a path record id; its spans are the caption). Ids match
  `[a-z0-9][a-z0-9-]*`, unique per document.
- **Claims to text**: a span with `claim` is that claim's rendered text. In drafts, `claim` is the draft `key`; save
  rewrites it to the id. A claim may back several spans; a claim no span shows is a warning.
- **Plain text** (what DocumentAnchor offsets index): section title, blank line, then each block's spans joined,
  blocks separated by a blank line, sections separated by a blank line (`mapdoc.plain_text`).
  `revision` = first 12 hex of sha256 of the plain text plus the flows' JSON, set by the script; annotations on
  the map re-anchor when it changes.
- Answers use the same `spans` (or plain `text`); `answer:<id>` plain text is the spans joined.

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
runtime trace: solid arrow), `unseen` (read or inferred only: dashed), or `blind_spot` (where the trace can't see,
e.g. C++ backward: dotted). `claim` is required: every hop is a claim and obeys the claim rules, so it is
anchor-cited or labelled. `returns`, `data`, `label` are optional strings. Loops with no hop are a warning.

## Activity log (avatars)

`activity.json`: `{schema: "honeyguide/activity", version: 1, entries: [...]}`; entry = `{id: "a_<12 hex>",
agent, question (id | null), status (one line, <= 200 chars), state: "working"|"done"|"failed", started_at,
updated_at, ended_at}`. The page shows `working` entries as animated avatars beside their thread (map-wide when
`question` is null) and recently ended ones for 10 minutes. Ended entries beyond the newest 200 are dropped.

## Session state

`session.json`: `{schema: "honeyguide/session", version: 1, last_visit, previous_visit, refresh_log: [{at, base,
target, counts, note}]}`. The page posts a visit on load; "N claims re-checked since your last visit" counts
claims with `checked_at > previous_visit`.

## Page server

`honeyguide serve` binds `127.0.0.1` only. It refuses any request whose `Host` is not `127.0.0.1:<port>` or
`localhost:<port>` (DNS rebinding), and every `/api/` request must carry `X-Honeyguide-Token` (embedded in the
served page; stored `0600` in the memory dir, kept across restarts). POSTs also need `Content-Type:
application/json` and, when an `Origin` header is sent, the same origin. The page never starts Claude: posts
land in the inbox and the session's `watch` wakes the Guide.

| method, path | body / query | result |
|---|---|---|
| GET `/` | | placeholder page (T7.3 replaces it) |
| GET `/api/state` | | repo id, HEAD, map commit, counts, `previous_visit`, `rechecked_since_visit`, refresh log |
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
