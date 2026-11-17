# Honeyguide demo video

- `honeyguide-demo.mp4`: 114.4 s, 1920x1200, 30 fps, H.264 (yuv420p, faststart), 8.7 MB.
- `honeyguide-demo.gif`: 23.6 s of the focus -> Ask -> answer loop (click `gpt.py` on the component map, focus mode, "Ask
  about this component", send; the session answers at x40; the answer lands; the Checker and repair at x60; 18 of 18
  pass), 960 px, 10 fps, 4.2 MB. Rendered by `cut.py ... gif` from the same take as the video.

Everything on screen is real: the map page (commit 398c248) served by `honeyguide serve` on port 8782 on the real
nanochat map (karpathy/nanochat at `92d63d4`, the Cartographer's map after its repair pass and the compute-rule
re-check, with its repo card saved), real clicks, keys and wheel events sent to it over the Chrome DevTools
Protocol, and one answer written by a real Claude Code session (the plugin from a checkout of this repo at
398c248). Headless Chrome has no cursor, so the cursor and click ripples are drawn into the frames from the logged
pointer events.

## Shots

| out (s) | shot | speed | source |
|---|---|---|---|
| 0.0 | title card | - | `cards.py` |
| 3.0 | payoff: the page top, the repo card (name, link, README line, language bar, licence, contributors, history, "Up to date at 92d63d4 · 282 claims") | x1 | `shoot_v4.py --only payoff` |
| 8.0 | install card (the README's install lines; labelled "from the README") | - | `cards.py` |
| 12.4 | clock card: how this map was made (the real command, abridged with "…"; 31 min explore + 15 min repair + 20 min re-check; their costs; 260 claims, 256 pass, 4 "Needs a look") | - | `cards.py`, numbers parsed from `outputs/runs.txt` |
| 18.4 | navigate: scroll the Overview (the outline's scroll-spy moves Purpose -> What it can do), "/" -> Find "window pattern" (4 matches), pick the GPT model's Design match, Esc (the outline returns, "GPT model" marked), the trap sentence, hover `nanochat/gpt.py:301–313` -> preview, point at GitHub (pinned to `92d63d4e8bb4`, lines 301-313) | x1 | `shoot_v4.py --only nav` |
| 48.0 | live: outline -> Component map (bands, main paths), click `gpt.py` -> focus mode, scroll to the focus card (called by 3, calls 1), "Ask about this component" -> panel with the question prefilled, Ask; "Waiting for the Guide" | x1 | `shoot_live.py --component mod-gpt`, take A |
| 72.3 | the session claims it, Honey routes it to the **Investigator**, which reads `gpt.py` and its callers and records the answer | **x20** (112 s real) | takes A + B01, PiP from `answer-q1.jsonl` |
| 77.9 | the answer lands in the thread | x1 | take B01 |
| 81.3 | the Checker re-reads 18 claims (14 pass, 4 flagged), the Investigator repairs the 4, the Checker re-checks them | **x35** (204 s real) | takes B01-B03, PiP |
| 87.1 | the checked answer (still): "14 of 18 passed at once; 4 repaired and re-checked. Now 18 of 18 pass." | x1, held 3.4 s | take B03 |
| 90.6 | a flow swimlane ("What happens when you type a message into scripts/chat_cli.py"): open it, Expand to full screen, + (106%), Ctrl+scroll at the pointer (128%), drag to pan into the engine and model lanes, Fit (85%), Esc | x1 | `shoot_v4.py --only flow` |
| 109.4 | closing card: logo, install, github.com/bearbearyu1223/honeyguide (public soon) | - | `cards.py` |

The closing card says "(public soon)" because the video was recorded before this repo went public.

Sped-up stretches carry a yellow "xN" badge in the top right, and the terminal shows the same badge. The claim
count on the last live caption is read from the saved answer by `cut.py` (`honeyguide claims list`); the run
minutes and costs on the clock card are parsed from `outputs/runs.txt` by `cards.py`.

## The real runs

| run | what | wall clock | cost (API list price, on a subscription) |
|---|---|---|---|
| explore (earlier, not replayed) | run 2: `claude -p "/honeyguide:honeyguide start over …"`, Cartographer + Checker | 31.1 min | $13.42 |
| repair (earlier, not replayed) | repair pass, 2 rounds | 15.3 min | $6.92 |
| re-check (earlier, not replayed) | compute-rule re-check of 117 value claims, then repair | 19.7 min | $9.19 |
| live `q_1a900486f311` | "What does gpt.py do, and how do the components around it use it?" (prefilled by "Ask about this component" on `gpt.py`), Guide -> **Investigator** -> answer `r_17a6293056b8` (18 claims) -> Checker: 14 supported, 4 not supported -> repair round 1 by the Investigator (4 claims changed, none retired) -> Checker re-check: 4 of 4 supported; 18 of 18 pass | 5.3 min (316 s, 19 turns) | $2.35 |

The first three rows are quoted from `outputs/runs.txt`. Map claims (`honeyguide status --json`, before the live
question): 260 map claims, 282 claims in all (map + two earlier answers), 268 supported, 14 not supported. After it:
260 map claims, 300 in all, 286 supported, 14 not supported. The repo card in the payoff shot was recorded before
the live question, so it says 282.

The live run was a batch session (`claude -p`, `answer.sh`) standing in for an interactive session's Monitor
watcher; the terminal's title says "batch session". The recording script started it right after the question was
sent, so the page recording and the session run on one clock. The question and its answer stay in the nanochat
map's inbox. One live question was asked (the limit was two).

## What the terminal picture-in-picture shows

`term.py` renders the session's own stream-json events (`answer.sh` stamps each with the time it was received):
the Guide's and each subagent's tool calls (subagents indented under a bar), the Guide's messages, and the first
line of each tool result. Abridged, never invented: long lines end in "…", JSON results are compacted to one line,
a file read is shown as its line count ("(556 lines)"), a subagent's hand-back as "(the subagent's report)", and
home paths are shortened (`~/…/nanochat`, `~/.honeyguide/…`, `~/.claude/projects/…/`). The clock is real time
since the session started. One real error shows in red: the Investigator's first `answer record` call failed
(exit 1); it fixed its draft and recorded the answer 38 s later.

## Reproduce

Needs: a nanochat clone at 92d63d4 with its map built and served (`honeyguide serve --repo <clone> --port 8782`),
its repo card saved (`honeyguide repo-info --repo <clone> --save`), a checkout of this repo at 398c248 for the
plugin and the CLI, Chrome, ffmpeg, uv. `answer.sh`, `cut.py` and `shoot_live.py` name the two paths at the top;
set them to yours. Keep the Mac awake while recording (`caffeinate -ims`): idle maintenance sleep froze
two early takes for 15 minutes each. From `demo/`, with `REC` a scratch folder (the raw takes are about 1 GB of
2880x1800 JPEGs):

```bash
uv run --project .. python cards.py $REC/cards                       # clock numbers from ../outputs/runs.txt
uv run --project .. python shoot_v4.py $REC/take                     # payoff, nav, flow
uv run --project .. python shoot_live.py $REC/live --tag q1 --component mod-gpt --dry   # rehearsal, sends nothing
uv run --project .. python shoot_live.py $REC/live --tag q1 --component mod-gpt         # the live take (a real run)
uv run --project .. --with pillow python cut.py $REC honeyguide-demo.mp4
uv run --project .. --with pillow python cut.py $REC $REC/gif-source.mp4 gif
ffmpeg -i $REC/gif-source.mp4 -vf "fps=10,scale=960:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff" $REC/pal.png
ffmpeg -i $REC/gif-source.mp4 -i $REC/pal.png -lavfi "fps=10,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" honeyguide-demo.gif
```

Each live question costs a real Claude Code run (`--max-budget-usd 8`). Every Chrome runs under
`perl -e 'alarm 120; exec @ARGV'` (via `tests/cdp.py`), so a live run longer than one Chrome is recorded as several
takes on one clock: take A (component map, focus, Ask, send, then the first ~80 s of the session), then B01, B02,
B03, each reopened on the same thread at the same scroll position, ~2 s apart. The gaps fall inside the sped-up
stretches; the focus mode does not survive a reopen, so after the first gap the map behind the panel is unfocused.

Files: `rec.py` (CDP screencast recorder, eased pointer, text selection by phrase), `shoot_v4.py` (payoff, nav,
flow), `shoot_live.py` (the live take), `answer.sh` (the batch session), `term.py`
(the PiP), `cards.py`, `compose.py` (frames, cursor, captions, badge, ffmpeg), `cut.py` (the edit).

## Cut or not shown live

- The explore, repair and re-check runs (66 minutes in all) are not replayed: there is no transcript of them, only
  their result files. The clock card shows their real minutes and costs from `outputs/runs.txt`.
- The install lines are shown as a card quoted from the README, not typed in a terminal.
- Sped up, with badges: the session's routing and answering (112 s at x20, 5.6 s on screen) and the Checker plus
  the repair pass (204 s at x35, 5.8 s). In the GIF: the scroll to the focus card at x2, the answering at x40, the
  Checker and repair at x60. Nothing in the live segment is cut: take A and B01-B03 are one run on one clock, with
  ~2 s Chrome reopens inside the sped-up stretches.
- After the first reopen the map behind the panel is no longer in focus mode (a reopened page starts unfocused),
  and the pointer is parked over `tokenizer.py`, so its hover card shows; the cut draws the parked pointer there.
- The payoff's repo card says 282 claims: it was recorded before the live question added 18.
- Light theme only.
- Found while recording, and fixed since (commit dd38ce9): "Ask about this component" on a component with several
  files prefilled its name with the "+N files" badge text, e.g. "What does engine.py +1 do, …"; it now reads
  "engine.py (and 1 more file)". The demo uses `gpt.py` (one file), whose question read correctly.
