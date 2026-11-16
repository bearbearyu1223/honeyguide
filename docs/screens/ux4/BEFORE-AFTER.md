# UX v4 (T7.17 + T7.18): before and after

All "after" shots are the REAL maps, served from copies of the stores (nanochat at `92d63d4` with its two live
answers; waku-agent at `2c7e7e6`), 1440x900 at 2x, light and dark, by `docs/screens/shoot_ux4.py`. The "before"
shots in `before/` are the T7.16 page on the same nanochat map, taken just before this change. Design notes:
`docs/design/ux-v4.md`.

**Review r2 (re-shot, nanochat only):** `nanochat-{top,module,graph-focus,flow-fullscreen,panel}-{light,dark}.png`
were re-taken by `shoot_ux4.py --maps nanochat` on a copy of the store after the re-check (map revision
`323cb08936ea`, three live answers), with three page fixes: a flow's return arrow goes back to the hop's caller (row 7
of `chat-reply` returned to `chat_cli.py`; it now returns to `engine.py`), the focus card names a multi-file component
with its "+N files" chip, and the repo card's foot says "N claims on the map, M in answers". Focus mode is now on
`gpt.py` with the whole map in frame; the flow is zoomed out until the whole swimlane is on screen (2880x1360). The
waku-agent shots are unchanged.

Look first: `design-component-graph.png`, `nanochat-graph-focus-light.png`, `waku-graph-fullscreen-zoomed-dark.png`,
`nanochat-top-light.png`.

| what | before | after |
|---|---|---|
| Side by side (light) | | `design-overview-top.png`, `design-module.png`, `design-component-graph.png` |
| Top of the page: repo card | `before/overview-light.png`, `before/overview-dark.png` | `nanochat-top-{light,dark}.png`, `waku-top-{light,dark}.png` |
| Contents: sections only vs sub-sections + scroll-spy + Find | `before/module-light.png` (left rail) | `nanochat-contents-scrollspy-{light,dark}.png`, `waku-contents-scrollspy-{light,dark}.png` |
| A module | `before/module-{light,dark}.png` | `nanochat-module-{light,dark}.png`, `waku-module-{light,dark}.png` |
| The component graph, default | `before/graph-{light,dark}.png`, `../t7.16/graph-top-to-bottom-{light,dark}.png` | `nanochat-graph-{light,dark}.png`, `waku-graph-{light,dark}.png` |
| Focus mode (new) | none | `nanochat-graph-focus-{light,dark}.png`, `waku-graph-focus-{light,dark}.png` |
| Full screen, zoomed (new) | none | `nanochat-graph-fullscreen-zoomed-{light,dark}.png`, `waku-graph-fullscreen-zoomed-{light,dark}.png` |
| A flow swimlane | inline only (`../t7.16/overlay-light.png` for the Tracer overlay) | `nanochat-flow-fullscreen-{light,dark}.png`, `waku-flow-fullscreen-{light,dark}.png` |
| The panel with an answer | `../t7.16/answer-two-sentences-{light,dark}.png` | `nanochat-panel-{light,dark}.png`; waku-agent has no answers, so `waku-panel-*` shows "Ask about this component" prefilling the Ask box |

## What changed, per view

- **Top**: a bare title and a memory line became a repo card: link, README description, language bar (by lines of
  source), licence, top contributors (names only), GitHub counts with "as of" (here "Not fetched: gh is not signed
  in", since `gh` isn't signed in on this machine), history (created, last commit, commits, branch), "mapped at"
  the map's commit; the memory line sits at the card's foot.
- **Contents**: three section names became an outline with every Overview topic, the component map, each module by
  its short name and each flow; the current section and card are marked as you scroll; Find (`/`) filters it and
  finds text in the map. The evidence key folds under one row.
- **Map**: running text under rules became cards on a tonal canvas under sticky section headers; prose lines are capped
  at 35em (66-75 characters); contents and discussion are inset rounded panels like NotebookLM's.
- **Component graph**: 17 arrows on shared bus lines with a count on every line (7 crossings, shown at 57-98%)
  became three bands (entry points, stages, leaves), each edge its own curved route between its own ports, counts on
  hover, main paths by default (8 of 17 links on nanochat; 10 of 16 on waku-agent) with "Show all N calls", click to
  focus with a card of calls and "Ask about this component", zoom / pan / fit / full screen. Crossings (reported by
  the layout as `data-crossings-main` / `-all`; the tests check them against the drawn geometry): **nanochat 1 in
  the main paths** (11 with every call; T7.16 drew 7), **waku-agent 5** (16 with every call). At fit the map shows
  at 96% (nanochat) and 95% (waku-agent): its smallest text is 12.3 px or more on screen.
- **Swimlanes and the Tracer overlay** gain the same viewer: zoom, pan, fit and full screen.
