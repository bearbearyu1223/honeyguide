# Honeyguide demo video

- `honeyguide-demo.mp4`: 117.8 s, 1920x1200, 30 fps, H.264 (yuv420p, faststart), 13.4 MB.
- `honeyguide-demo.gif`: 23.4 s of the live loop (select, Ask, the session works, the answer lands), 960 px, 10 fps, 2.2 MB.
- `poster.png`: the first answer just landed beside its highlight, the real session in the corner (no caption).
- `STORYBOARD.md`: the plan this was recorded from.

Everything on screen is real: the real page served by `honeyguide serve` on the real nanochat map
(karpathy/nanochat at `92d63d4`, the Cartographer v2 map after its repair pass: 260 claims), real clicks and typing
sent to it over the Chrome DevTools Protocol, and answers written by real Claude Code sessions. Headless Chrome has
no cursor, so the cursor and click ripples are drawn into the frames from the logged pointer events.

## Shots

| out (s) | shot | speed | source |
|---|---|---|---|
| 0.0 | title card | - | `cards.py` |
| 3.0 | payoff: the finished map, Overview, Honey in the sidebar | x1 | `shoot_tour.py --only payoff` |
| 7.0 | install card (the README's install lines; labelled "from the README") | - | `cards.py` |
| 11.6 | clock card: how this map was made (the real command, abridged with "…"; 31 min + 15 min; costs) | - | `cards.py --runs`, from the runs' `start`/`end`/`result.json` |
| 17.0 | tour: Overview "Start here", Modules, gpt.py's Design paragraph (the window-pattern trap), hover `nanochat/gpt.py:302` -> preview, point at GitHub (pinned to `92d63d4e8bb4`, line 302) | x1 | `shoot_tour.py --only tour` |
| 36.9 | live question 1: select the trap sentence, Ask, type, send; "Waiting for the Guide" | x1 | `shoot_live.py --tag q1`, take A |
| 53.5 | the session picks it up: the Guide claims it and routes it to the Tracer; the Tracer reads | **x20** (98 s real) | takes A + B01, PiP from `answer-q1.jsonl` |
| 58.5 | the answer lands beside the highlight | x1 | take B01 |
| 61.7 | the Checker re-reads the cited lines | **x20** (82 s real) | take B01, PiP |
| 65.8 | the finished answer: hops with their marks, a "not supported" flag's note, "View as diagram", panning the swimlane | x1 | `shoot_answer.py`, recorded after run 1 finished |
| 89.8 | live follow-up: select words in the answer, Ask, type, send | **x2** | `shoot_live.py --tag q2`, take A |
| 98.2 | the session routes it to the Investigator, which searches | **x20** (71 s real) | take A, PiP from `answer-q2.jsonl` |
| 101.7 | the follow-up lands under the answer | x1 | take A |
| 104.9 | the follow-up after its check (caption: "Checked 57 s after it landed: 8 of 9 claims pass") | x1 | `shoot_followup.py`, recorded after run 2 finished; the 58 s Checker stretch itself is not shown |
| 112.8 | closing card: logo, install, github.com/bearbearyu1223/honeyguide (public soon) | - | `cards.py` |

Sped-up stretches carry a yellow "xN" badge in the top right, and the terminal shows the same badge. Every claim
count on a caption (4 of 13, 8 of 9) is read from the saved answers by `cut.py` (`honeyguide claims list`), and the
seconds are measured from the take logs.

## The real runs

| run | what | wall clock | cost (API list price, on a subscription) |
|---|---|---|---|
| explore (earlier, not replayed) | `claude -p "/honeyguide:honeyguide start over …"`, Cartographer v2 + Checker | 31 min (03:11:40-03:42:45 UTC) | $13.42 |
| repair (earlier, not replayed) | `claude -p "/honeyguide:honeyguide refresh …"` repair pass, 2 rounds | 15 min (04:08:10-04:23:27 UTC) | $6.92 |
| live q1 `q_d7c4fd23c771` | Guide -> **Tracer** -> answer `r_95ea573d35fc` (13 claims) -> Checker: 4 supported, 9 not supported | 3.0 min (180 s, 12 turns) | $1.28 |
| live q2 `q_9b365ac5f974` (follow-up) | Guide -> **Investigator** -> answer `r_6c703482a61e` (9 claims) -> Checker: 8 supported, 1 not supported | 2.1 min (129 s, 11 turns) | $1.08 |

The two live runs were batch sessions (`claude -p`, `answer.sh`) standing in for an interactive session's Monitor
watcher; the terminal's title says "batch session". Each was started by the recording script right after the
question was sent, so the page recording and the session run on one clock. The questions and answers stay in the
nanochat map's inbox.

## What the terminal picture-in-picture shows

`term.py` renders the session's own stream-json events (`answer.sh` stamps each with the time it was received):
the Guide's and each subagent's tool calls (subagents indented under a bar), the Guide's messages, and the first
line of each tool result. Abridged, never invented: long lines end in "…", JSON results are compacted to one line,
a file read is shown as its line count ("(520 lines)"), a subagent's hand-back as "(the subagent's report)", and
home paths are shortened (`~/…/nanochat`, `~/.honeyguide/…`, `~/.claude/projects/…/`). The clock is real time
since the session started.

## Reproduce

Needs: the nanochat map served (`honeyguide serve --repo ~/Documents/GitHub/honeyguide-targets/nanochat --port 8782`),
the frozen plugin copy at `~/Documents/GitHub/honeyguide-run` (`aa42ce5`), Chrome, ffmpeg, uv. From `demo/`, with
`REC` a scratch folder (the raw takes are about 1.4 GB of 2880x1800 JPEGs):

```bash
uv run --project .. python cards.py $REC/cards --runs <folder with run2-nanochat/ and repair-nanochat/>
uv run --project .. python shoot_tour.py $REC/take1
uv run --project .. python shoot_live.py $REC/live --tag q1 --a "The window pattern is the trap" --b "sees all of it" \
  --question "Where is the quarter computed, and how does each layer's window size reach the attention kernel?"
uv run --project .. python shoot_answer.py $REC/take1/answer --q <q1 id>
uv run --project .. python shoot_live.py $REC/live --tag q2 --parent <q1 id> --a "At 2048 that is 512" \
  --b "the inline comment says" --question "Does anything else still say 768, or a third of the context: docs, tests, help text, or this map?"
uv run --project .. python shoot_followup.py $REC/take1/followup --q <q2 id>
uv run --project .. --with pillow python cut.py $REC honeyguide-demo.mp4
uv run --project .. --with pillow python cut.py $REC poster.png poster
ffmpeg -ss 38.1 -t 23.4 -i honeyguide-demo.mp4 -vf "fps=10,scale=960:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff" pal.png
ffmpeg -ss 38.1 -t 23.4 -i honeyguide-demo.mp4 -i pal.png -lavfi "fps=10,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" honeyguide-demo.gif
```

Each live question costs a real Claude Code run (`--max-budget-usd 8`). Every Chrome runs under
`perl -e 'alarm 120; exec @ARGV'` (via `tests/cdp.py`), so a live run longer than one Chrome is recorded as several
takes on one clock: take A (the question, then the first ~90 s), then B01, B02, … each reopened on the same thread
at the same scroll position, ~1.5 s apart. The gaps fall inside the x20 stretches.

Files: `rec.py` (CDP screencast recorder, eased pointer, text selection by phrase), `shoot_*.py` (the takes),
`answer.sh` (the batch session), `term.py` (the PiP), `cards.py`, `compose.py` (frames, cursor, captions, badge,
ffmpeg), `cut.py` (the edit).

## Cut or not shown live

- The explore and repair runs (46 minutes) are not replayed: there is no transcript of them, only their result
  files. The clock card shows their real command and clock instead.
- The install lines are shown as a card quoted from the README, not typed in a terminal.
- The Checker stretch of the follow-up (58 s) is cut; its result is shown in a take recorded after the run.
- The answer walkthrough (65.8 s) and the follow-up result (104.9 s) were recorded after their runs ended, from the
  saved state; nothing on them changed in between except the next question being asked.
- Light theme only.
