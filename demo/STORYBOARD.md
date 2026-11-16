# Honeyguide demo v2 (UX v4): storyboard

Target: 90-120 s, 1920x1200, 30 fps, H.264, under 15 MB; a 15-25 s GIF of the focus -> Ask -> answer loop (960 px,
under 8 MB) and a poster. Everything on screen is the real page (UX v4, commit 398c248) served by the real
`honeyguide serve` on port 8782 on the real nanochat map (karpathy/nanochat at 92d63d4, after the repair pass and
the compute-rule re-check, its repo card saved), and an answer written by a real Claude Code session (the frozen
plugin copy `honeyguide-run` at 398c248). Headless Chrome has no cursor, so the cursor and click ripples are drawn
in from the logged pointer events. The previous cut (T7.14, UX v3) is kept in `v1/`.

| # | shot | the viewer takes away | how it's produced | caption | s |
|---|---|---|---|---|---|
| 0 | Title card: Honey logo, "Honeyguide" | what this is | rendered card | Learn a repo as a map. Ask it questions. | 3 |
| 1 | Payoff: the page top, the repo card (name, link, README line, language bar, licence, contributors, history, "Up to date at 92d63d4 · N claims"), contents on the left | the end product: a clean, cited map of a real repo | CDP screencast, `shoot_v4.py --only payoff` | A map of karpathy/nanochat, with its repo card. | 4 |
| 2 | Start: install lines (from the README) and the command; then a clock card with run 2's explore, the repair pass and the re-check (minutes and cost quoted from `outputs/runs.txt`), claim counts from `honeyguide status --json` | how to start, and what the map cost in time and money | `cards.py --runs-txt ../outputs/runs.txt --status <status.json>` | Install, then ask Claude Code to explore. / This map: 31 min, then 15 + 20 min of checking. | 10 |
| 3 | Navigate: scroll the Overview cards (the outline's scroll-spy follows), press "/" and type "window pattern", pick the GPT model match, read the Design paragraph's trap sentence, hover its code chip -> preview pinned to 92d63d4 with its GitHub link | the outline always says where you are; Find takes you to any term; every sentence opens its lines | CDP screencast, `shoot_v4.py --only nav` | The outline follows you. / Press / to find any term. / Design: the sharp edge you'd hit first. / Every citation opens its lines, pinned to the commit. | 22 |
| 4 | Component map: outline -> Component map (bands: Entry points, Stages, Leaves; main paths); click `engine.py` -> focus mode (callers and callees stay, the rest fades), the focus card; "Ask about this component" -> the panel opens anchored to its module, the question prefilled | the map of how components call each other is a way into questions | take A of `shoot_live.py --tag q1 --component mod-engine` | Main paths between components. / Click one: focus mode. / Ask about this component: the question is written for you. | 16 |
| 5 | Live loop (same take, same run): press Ask; "Waiting"; the batch Claude Code session in the terminal PiP claims it, Honey routes it, a subagent reads (sped up, xN badge); the answer lands in the panel at x1; the Checker re-reads (xN) and stamps the claims | you ask on the page; your Claude Code session answers, cited and checked | `shoot_live.py` takes A, B01..; `answer.sh` (stream-json with receive times), PiP via `term.py` | Ask. Your Claude Code session picks it up. (xN) / The answer lands, cited. / The Checker re-reads every cited line. | 22 |
| 6 | A flow swimlane: outline -> "What happens when you type a message…", open it, Expand to full screen, zoom in (+, then Ctrl+scroll at the pointer), drag to pan, Fit, Esc | every diagram is zoomable and full screen | CDP screencast, `shoot_v4.py --only flow` | Every diagram: full screen, zoom and pan. | 14 |
| 7 | Close: logo, install, github.com/bearbearyu1223/honeyguide (public soon) | where to get it | rendered card | - | 5 |

Honesty rules: waiting is sped up only with a visible "xN" badge (on the page and the terminal); a skipped stretch
carries a clock card; the PiP shows only real events from that session, abridged with "…", titled "batch session";
the explore, repair and re-check runs are not replayed (no transcript): shot 2 shows their real clock and cost from
`outputs/runs.txt`. One live question (at most two), each `--max-budget-usd 8`. One take is one run: shots 4 and 5
are one continuous take of one run.

## As recorded (changes from the plan)

- Shot 4 focuses `gpt.py`, not `engine.py`: a rehearsal (`--dry`, nothing sent) showed that "Ask about this
  component" on a component with several files prefills its name with the "+N files" badge text ("What does
  engine.py +1 do, …"), a page bug outside this task. `gpt.py` is one file and is called by three components.
- The Guide routed the prefilled question to the **Investigator**. The Checker passed 14 of 18 claims, the
  Investigator repaired the 4 flagged ones (SKILL.md section 8, now part of `answer.sh`'s prompt), and the re-check
  passed all 4: 18 of 18. One run, 5.3 min, $2.35 at API list price.
- Shot 6 zooms with + once and Ctrl+scroll at the pointer (106% -> 128%), pans into the engine and model lanes,
  then Fit and Esc.
- Length 114.4 s (planned 90-120 s). Details and timings: README.md.
