# Honeyguide demo: storyboard

Target: about 90 s, 1920x1200, 30 fps, H.264, under 15 MB; a 15-25 s GIF of the live loop (960 px) and a poster.
Everything on screen is the real page served by the real `honeyguide serve` (port 8782) on the real nanochat map
(karpathy/nanochat at 92d63d4: 260 claims, all supported after the repair pass), and answers written by a real
Claude Code session. Headless Chrome has no cursor, so the cursor and click ripples are drawn in from the logged
pointer events.

| # | shot | the viewer takes away | how it's produced | caption | s |
|---|---|---|---|---|---|
| 0 | Title card: Honey logo, "Honeyguide" | what this is, in one line | rendered card | Learn a repo as a map. Ask it questions. | 3 |
| 1 | Payoff: the finished nanochat map, Overview, Honey in the sidebar | the end product is a readable, cited map | CDP screencast, `shoot_tour.py --only payoff` | A map of karpathy/nanochat. Every sentence cites its lines. | 4 |
| 2 | Start: the install lines (from the README), then the real command that made this map, then a clock card | how to start, and what it costs in time | text card from the README; the real `claude -p "/honeyguide:honeyguide start over ..."` line from the run script; clock card from the run's start/end/result.json | Install the CLI and the plugin, then ask Claude Code to explore. / This map: 31 min, then a 15 min repair pass. | 10 |
| 3 | Tour: Overview "Start here", gpt.py's Design paragraph (the window-pattern trap), hover a code chip -> preview, GitHub link pinned to the commit | the map tells you where to start and where the sharp edges are, and every claim opens its lines | CDP screencast, `shoot_tour.py --only tour` | Start here. / Design: the sharp edge you'd hit first. / Every citation opens the exact lines, pinned to the commit. | 15 |
| 4 | Live loop: select the trap sentence, Ask, type a real question, send; the page shows it waiting, then Honey routes it and the Investigator works; PiP terminal of the real Claude session answering it, sped up (marked xN) | you ask on the page; your Claude Code session does the work | `shoot_live.py --tag q1` (takes A, B..) while `answer.sh` runs `claude -p "/honeyguide:honeyguide watch ..."` with stream-json; PiP rendered from its timestamped events, abridged with "…" | Select any text and Ask. / Your Claude Code session picks it up. (xN) | 25 |
| 5 | The answer lands beside the highlight, with evidence marks; the Checker stamps its claims | answers are cited and checked, like the map | same takes | The answer lands beside your highlight. / Then the Checker re-reads every cited line. | 12 |
| 6 | Follow-up: select words in the answer, ask "What happens when ...", the Tracer answers, "View as diagram" (swimlane) | flow questions go to the Tracer and come back as a diagram | `shoot_live.py --tag q2 --parent <q1>`, a second real session; if too slow or costly, a clock card or the map's own flow labelled as such | "What happens when ..." goes to the Tracer. / ...and comes back as a diagram. | 15 |
| 7 | Close: logo, install command, github.com/bearbearyu1223/honeyguide (public soon) | where to get it | rendered card | Public soon. | 6 |

Honesty rules applied: waiting is sped up with a visible "xN" badge; any skipped stretch carries a clock card; the
terminal PiP shows only real events from that session (abridged with "…"), and its label says it is a batch
(`claude -p`) session run for this recording; the explore itself is not replayed (there is no transcript of it):
shot 2 shows its command and its real clock.

## As recorded (changes from the plan)

- Shot 4's question ("Where is the quarter computed, and how does each layer's window size reach the attention
  kernel?") was routed by the Guide to the **Tracer** (a "how does X get from A to B" question), so its answer
  already had a swimlane: "View as diagram" moved into shot 5.
- Shot 6's follow-up therefore asks a search question ("Does anything else still say 768 ...?") and shows the
  other route, to the **Investigator**. Its answer found a slip in the map itself (claim `c_20b0bb0d778f` repeats
  the stale "768").
- The Checker passed 4 of 13 claims on the Tracer answer (answers get no repair pass); the video says so and shows
  one flag's note rather than implying everything passed.
- Length 117.8 s (planned ~90 s). Details and timings: README.md.
