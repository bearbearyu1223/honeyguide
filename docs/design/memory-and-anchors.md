# Memory and anchors (design note)

The foundation under the Honeyguide agents and map page: what a claim is, how it points at code, where it is
saved, and what happens to it when the code changes: the data model, source links, and memory and refresh. Standard
library only; everything exact is a script, never an agent.

## Data model

Two kinds of anchor, for two different jobs.

- **CodeAnchor** (evidence; points at source lines): `path` (repo-relative POSIX), `anchor` (the text the agent
  quoted, one or more lines), `start`/`end` (resolved 1-based line range), `commit` (full sha the lines were read
  at), `hash` (sha256 over the cited lines, trailing whitespace stripped, 16 hex), `symbol` (the enclosing Python
  definition, e.g. `Agent.run`, when there is one). An agent supplies only path + anchor text (+ optionally
  `end_anchor` or `extent="block"` for a whole definition); the script fills in everything else by reading
  `git show <commit>:<path>`. Line numbers are never typed by an agent.
- **DocumentAnchor** (annotation; points at text on the page): `doc` (`map` or `answer:<response id>`),
  `revision`, `quote`, `start`/`end` (character offsets), `context` (hash of 32 characters either side). On
  regeneration it re-anchors by quote, then by context to break ties; anything else is reported *unresolved* and
  shown flagged, never attached to the nearest text.

Records (plain JSON objects; ids are `<prefix>_<12 hex>`):

| record | key fields |
|---|---|
| Claim (map note or one claim inside an answer) | id, text, evidence label, code anchors, `check` (unchecked / supported / not_supported / skipped), `freshness` (current / stale / retired) + reason |
| Annotation | id, kind (`note` or `question`), DocumentAnchor, author, created_at, text; notes add `share_with_agents` (default false) |
| Response | id, parent (question id), agent, text, claims, generation metadata |
| FollowUp | *not a separate record*: a question Annotation whose anchor is on an answer (`doc = answer:<id>`) and that carries `parent_response`. This holds every FollowUp field in the original model (parent response, selected offsets, question text; the resulting response points back through `parent`) without a fourth list to keep in sync. |

Evidence labels: `read_in_source`, `asserted_by_test`, `docs`, `seen_at_runtime`, `inferred`,
`searched_not_found`, `general_knowledge`. The last two need no anchor; refresh and the Checker skip
`general_knowledge`.

## On disk

`$HONEYGUIDE_HOME` (default `~/.honeyguide`) / `<repo-id>/`, never inside the checkout:

```
repo.json     identity: id, normalized remote, root commit, all roots
map.json      {schema, version, commit, document, claims[]}        the Cartographer's map
answers.json  {schema, version, questions[], responses[]}           questions, follow-ups, answers
notes.json    {schema, version, notes[]}                            personal notes
.lock         flock target
```

Every file carries `"schema": "honeyguide/<layer>"` and `"version": 1`. A reader refuses a newer version
rather than rewriting it with fields it doesn't know, and refuses a file it can't parse rather than replacing it.

## Repo identity

`id = <normalized remote> + root commit`, made filesystem-safe: `github.com__huggingface__smolagents__dfd9609c26cc`.

- Remote: `origin` if it exists, otherwise the alphabetically first remote. Normalization drops the scheme
  (`https`, `http`, `ssh`, `git`, `git+ssh`), any `user:password@`, the ssh port, a trailing `.git` and `/`, and
  turns scp form `git@host:owner/repo` into `host/owner/repo`. The host is lowercased; on github.com the whole path
  is too (GitHub names are case-insensitive). So the https and ssh clones of one repo get one id. Credentials in a
  remote URL are never written anywhere.
- No remote, or a remote that is a local path: the remote part is `local`. Two unrelated local repos still differ by
  root commit.
- Several root commits (merged-in histories): the root reached by following **first parents** from HEAD. A later
  merge of another history doesn't change it, as "smallest sha" or "oldest" could. All roots are kept in
  `repo.json` for diagnosis.
- A fork with its own remote is a different repo id, as the spec implies; `import` moves memory between them.

## Source links

Built from a resolved CodeAnchor by the script, never by an agent.

- **GitHub**: `https://github.com/<owner>/<repo>/blob/<sha>/<path>#L<a>-L<b>` (`#L<a>` for one line), path
  segments URL-quoted. Returned only when the chosen remote is github.com (https or ssh forms) **and** the commit is
  on that remote. The check is local, no network: `git for-each-ref --contains <sha> refs/remotes/<remote>`, i.e.
  "some remote-tracking branch of that remote contains it". It can be out of date in both directions: a commit
  pushed by someone else since the last fetch reads as not pushed (link hidden; the safe direction), and a branch
  force-pushed away since the last fetch still reads as pushed (rare; `git fetch` fixes both). `ls-remote` was
  rejected: it only lists branch tips, so containment would need a fetch anyway.
- **Editor**: `vscode://file/<abs path>:<line>:1` and `cursor://file/<abs path>:<line>:1`, at the anchor's start
  line in the local checkout. They open the working copy, so they are exact only when the anchor was refreshed to
  HEAD and the file is clean; the page should say so otherwise.

## Refresh

Input: saved claims (map + answer claims) and a target commit B (default HEAD; a dirty tree is compared against
HEAD with a warning, untracked files ignored). Each anchor is refreshed from **its own** commit A, so answers
saved on different days refresh correctly; diffs are computed once per distinct A
(`git diff --name-status -M A B`).

Per anchor, in order:

1. File unchanged between A and B: **unchanged** (nothing read).
2. File deleted: **retired** (`file deleted`).
3. Renamed (`R`): follow the rename, then continue with the new path.
4. Re-read the file at B. The same span hash at the same place: **unchanged** (or **moved** if the path changed).
5. The same span hash elsewhere: exactly one place (or exactly one inside the anchor's symbol): **moved**, line
   numbers updated. Several identical places: **stale** (`ambiguous`), never a guess.
6. Otherwise the cited lines changed. If the symbol still exists, or the anchor text is found exactly once:
   **stale**, with the new candidate location for the Checker. Symbol gone and anchor text gone: **retired**
   (`code gone`). Anchor text found several times and no symbol to narrow it: **stale** (`ambiguous`).
7. The anchor's commit isn't in this clone (memory imported from another checkout): **stale** ("fetch it, then
   refresh"), never a crash and never served.

A claim's state combines its anchors: all unchanged -> unchanged; unchanged/moved only -> moved; all retired ->
retired; anything else (any stale, or some retired beside live ones) -> stale. Claims with no code anchors are
`unanchored` and untouched. Stale and retired claims are never served as fact: retrieval excludes them unless asked,
and then marks them. Applying a plan (a pure function) rewrites anchors of unchanged/moved claims to commit B with
new lines; stale claims keep the old anchor (what was checked) plus the candidate location (with a hash of the
candidate lines), and reset `check` to `unchecked`, except a claim already stale whose candidates are identical
(it keeps the Checker's re-check verdict, so an unrelated commit doesn't re-queue it).

**Applying it**: `honeyguide refresh apply` plans and applies in one hold of the store's lock, from the
claims as saved at that moment, advances the map's commit to B, and logs `{base, target, counts}` in the
session; the map is written after the answers, so a crash leaves it behind HEAD and a re-run finishes. The
Checker then re-checks each stale claim at HEAD: still true -> `verdict set` with new anchors, and the claim is
current again; not true -> it stays stale (flagged) and the Cartographer rewrites stale map claims, retiring the
old ones (`claims retire`, or `retire` in the same `claims save`). Retired claims stay in the store, shown struck
through, and are never retrieved. Contract details: `agent-contract.md`.

**Uncovered code**: in every added/modified/renamed `.py` file, the outline at B is module-level functions,
classes and methods of top-level classes (a class's own unit excludes its methods' lines). A unit is *new or
changed* if its qualified name didn't exist at A or its hash differs; it is *uncovered* if no unchanged, moved or
stale anchor at B overlaps it (for a class, its own lines, not its methods'). That list is what the Cartographer
maps next, and nothing else. Non-Python changed files are listed as "changed, no outline".

## Retrieval

Input: the selection's claims (their anchors), files and symbols mentioned in the question, and its text. Scoring:
overlapping lines in the same file 3, same symbol 2, same file 1. Keyword overlap is a fallback used only when no
anchor matches. Returns map claims and answers (with the matching claims). Excluded by default: stale and retired
claims, claims the Checker marked `not_supported`, and every note not marked `share_with_agents`. With
`include_stale=True`, stale/retired claims come back marked, never mixed in silently. A shared note is returned
when it is tied to a retrieved claim (`claim_ids`), sits on a retrieved answer, or shares keywords with the
question. `retrieve()` is the agent-facing call and the filter lives there; the agents' briefs hand them notes only
through it (the store itself will load any layer for the page).

## Concurrency and crash safety

The page server and the session both write. Every write is read-modify-write inside an exclusive `flock` on
`.lock` (10 s timeout, then an error, not a hang), and lands by temp file in the same directory + fsync +
`os.replace` + directory fsync, so a crash leaves the old file or the new one, never half of one. Readers take no
lock; a rename is atomic. Stray temp files from a crash are ignored. Windows has no `fcntl`; writes stay atomic
but unserialized (not a target).

## Export and import

One JSON file (`schema: honeyguide/export`): identity + the three layers. Notes not shared with agents are left out
unless `--include-private-notes` (export is for sharing). Import checks the repo id (`--force` to cross forks),
merges by record id, keeps the local record on a clash and reports counts.

## Out of scope

Embeddings; non-Python outlines (other files are refreshed by hash and anchor text only); following code moved
*between* files without a git rename (it shows as retired + uncovered); refresh of the working tree's uncommitted
edits; network checks for "pushed"; multi-user merge beyond "local wins"; the map's document structure
(`document` is opaque here; see `agent-contract.md`).
