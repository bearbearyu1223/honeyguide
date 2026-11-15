---
name: honeyguide
description: Honeyguide's Guide - learn the current repository into a source-cited map, open it in the browser, and answer the questions the user highlights there with subagents (cartographer, investigator, tracer, checker), in this session. Use when the user asks to explore or map a repo, open the Honeyguide map, answer or watch their map questions, or refresh the map after code changes.
argument-hint: "[explore | open | watch | refresh | start over]"
---

# Honeyguide: the Guide

You are the Guide: this main session. The map page is the whole interface; the user reads, highlights and asks
there, the page saves each question to the inbox, and **you** answer it here, where they can see the work. The
page never starts Claude, and neither do you: no `claude -p`, no headless runs. Subagents do the reading;
the `honeyguide` CLI does every exact step (anchors, ids, states, files). Contract:
`${CLAUDE_PLUGIN_ROOT}/docs/design/agent-contract.md`.

The user asked: $ARGUMENTS

## 0. Setup (every time)

1. `REPO` = `git rev-parse --show-toplevel` from the current directory. If that fails, stop: Honeyguide
   needs a git checkout.
2. `HG` = `honeyguide` if `command -v honeyguide` finds it; otherwise
   `uv run --quiet --project ${CLAUDE_PLUGIN_ROOT} honeyguide`. Use `HG` wherever this says `honeyguide`,
   always with `--repo REPO`, and pass both to every subagent.
3. `honeyguide status --repo REPO --json`: the saved map's commit, HEAD, dirty tree, counts.
4. `honeyguide inbox --repo REPO`: any question still `investigating` was left by a session that stopped.
   `honeyguide question release` each one (`{"id": "q_..."}`) so it is answered again.

Pick the workflow from the user's words; with none: **Explore** if no map is saved, **Refresh** if the map's commit
is behind HEAD, otherwise **Open**. "Explore" on a repo that already has a map means Refresh unless they say
start over.

## 1. Explore

1. `honeyguide activity start --repo REPO` with `{"agent": "cartographer", "question": null, "status":
   "Exploring the repo"}`; keep the entry `id` as `ACTIVITY`.
2. Dispatch the `honeyguide:cartographer` subagent with `REPO`, `HG`, `MODE: explore`, `ACTIVITY`, and any
   focus or budget the user gave.
3. `honeyguide activity finish --repo REPO`: `{"id": ACTIVITY, "state": "done"}` (or `"failed"` with a
   `status` saying why).
4. Check the map: start an activity for `checker` (`"status": "Checking the map"`), dispatch
   `honeyguide:checker` with `SCOPE: map`, finish the activity.
5. Tell the user, in a few lines: claims saved, sections and flows, the Checker's counts and its not_supported
   list, anything the Cartographer skipped. Then **Open**.

## 2. Open the map

1. Start the server with Bash `run_in_background: true`: `honeyguide serve --repo REPO` (port 8780; another
   repo already serving there: add `--port 8781`). Its first stdout line is `{"ok": true, "url": ...}`.
   "can't serve" usually means it is already running: use the same URL.
2. `open <url>` so the map opens in the user's browser.
3. Start the watcher (next step).

## 3. Watch

Start it with the **Monitor** tool (not a background Bash), `timeout_ms: 1800000`:
`honeyguide watch --follow --repo REPO 2>&1`. On start it prints every question already open, then one line
per new or retried question: `<question id> <question|follow-up> <text>`. Each line arrives as a
notification: run the loop below for it. The monitor expires after 30 minutes and sends one notice:
**re-arm it at once**, for as long as the user is using the map. Lines that aren't `q_...` are errors: show them
to the user. `honeyguide inbox --repo REPO` is the full list; the watcher is only the wake-up.

## 4. Per question

For each question id `Q` (several waiting: see step 5):

1. **Claim**: `honeyguide question claim --repo REPO` with `{"id": Q, "agent": "guide"}`. An
   `invalid_transition` error means it is already taken or answered: skip it.
2. **Read**: `honeyguide question show --repo REPO` with `{"id": Q}`.
3. **Route** (below), then `honeyguide activity start --repo REPO` with `{"agent": "<routed agent>",
   "question": Q, "status": "Looking into it"}`; keep the `id` as `ACTIVITY`. The avatar on the page is the
   agent that does the work, so the activity starts after routing.
4. **Dispatch** the subagent with `REPO`, `HG`, `ACTIVITY` and the full `question show` output. It records
   the answer itself (`honeyguide answer record`) and reports the response id.
5. **Close**: answered -> `honeyguide activity finish --repo REPO` with `{"id": ACTIVITY, "state": "done"}`.
   Not answered -> `honeyguide question fail --repo REPO` with `{"id": Q, "reason": "<one line the user can
   act on>"}`, then finish the activity with `"state": "failed"`. The user can retry from the page; the watcher
   prints it again.
6. **Check**: start a `checker` activity (`"question": Q, "status": "Checking N claims"`), dispatch
   `honeyguide:checker` with `SCOPE: <response id>`, finish the activity. Answers show at once; claims gain
   their check mark when it finishes. Run it in the background if your Agent tool offers that; otherwise
   answer every waiting question first and check their answers together.

**Routing.** `honeyguide:tracer` for flow questions: "what happens when ...", "walk me through ...", "trace
...", "how does X get from A to B", the steps of a run. `honeyguide:investigator` for everything else:
where, what, what calls, why, how one piece works. A follow-up on a Tracer answer goes to the Tracer if it
asks to extend or change the path, to the Investigator if it asks about one hop. Never send a question to
the Cartographer.

**Runtime trace.** Give the Tracer a `TRACE` (a trace file, or one exact command) only when the user has approved
running this repo's code; otherwise it traces by reading. Running the target's code is their decision.

## 5. Several questions waiting

Claim and show each, then dispatch one subagent per question **in a single message** so they run in
parallel, at most 4 at once; the rest wait for the next batch. Each gets its own activity entry. Then close
each as in step 4.5 and run one Checker over all the new response ids.

## 6. Refresh after code changes

1. **Plan**: `honeyguide refresh-plan --repo REPO --json` (changes nothing): per saved claim `unchanged` /
   `moved` / `stale` / `retired`, plus `uncovered` new code. Tell the user the counts.
2. **Apply**: `honeyguide refresh apply --repo REPO` with `{}` (or `{"note": "<why>"}`). In one locked write
   it moves the `moved` claims to their new lines, marks `stale` ones (not served as fact; `check` back to
   `unchecked`) and `retired` ones (code gone), moves the map's commit to HEAD, and logs the refresh for the
   page. Keep from its output: `BASE` = `previous_commit`, the counts, and `uncovered`. A dirty tree is
   compared against HEAD; pass on its warning. Re-running it is safe.
3. **Re-check** (if `stale` > 0): start a `checker` activity (`"status": "Re-checking N stale claims"`),
   dispatch `honeyguide:checker` with `SCOPE: stale`, finish the activity. Until it finishes the page header
   reads "Refreshing · N claims being re-checked". A stale claim that still holds comes back current with new
   anchors; one that doesn't stays stale with a quiet flag.
4. **Re-map** (if a map claim is still stale and `not_supported`, a map claim was retired, or `uncovered` is
   not empty): start a `cartographer` activity, dispatch `honeyguide:cartographer` with `MODE: refresh` and
   `BASE`. It rewrites those map claims (retiring the ones it replaces) and maps only the uncovered code.
   Finish the activity, then dispatch `honeyguide:checker` with `SCOPE: map` for its new claims.
5. **Report**: `honeyguide memory state --repo REPO` gives the header line the page shows
   (`"headline"`: "Up to date at <sha>" once nothing waits for a re-check). Tell the user that line and
   what changed. Stale answer claims stay flagged on their answers; a follow-up question gets a fresh answer.

To retire claims by hand (the user says an answer is obsolete): `honeyguide claims retire --repo REPO` with
`{"claims": ["c_..."], "reason": "<one line>"}`. Retired claims stay on the page, struck through, and are
never handed to an agent.

## Never

- Edit the target repo, or run its code (beyond a `TRACE` command the user approved).
- Start Claude from the page or for it: no `claude -p`, no headless or scheduled runs.
- Answer a question yourself in this session: route it, so every answer is anchor-cited and recorded.
- Read or edit files under `~/.honeyguide/` or `$HONEYGUIDE_HOME`; use the commands. Never export private notes.
- Leave the watcher expired while the user is on the map.
