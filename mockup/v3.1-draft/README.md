# Honeyguide map page: static mockup (v3.1)

`index.html` is one self-contained file (inline CSS and JS, no network, no build step, no web fonts fetched).
Everything in it is SAMPLE content: a made-up map of a small GPT training repo called `tinytrain`, with canned
answers. Open it in any browser:

    open mockup/index.html

v3 is v2's interaction model, unchanged, in the author's visual system (`feedback/2026-11-15-author-visual-design-recommendations.html`;
plan §3b "Visual system"), plus two additions agreed after v2 started: **source links** in the code preview and
the **memory state** (plan §3b "Source links", "Memory and refresh"). v3's screenshots are in `shots/v3/`, v2's in
`shots/v2/`, v1's in `shots/v1/` (v1 = commit 625a1ae, v2 = 7e16f77, v3 = 5fde9df).

**v3.1** adds the **flow diagrams** (plan §3b "Flow diagrams"): a swimlane sequence diagram for each flow and a
module graph in the Overview, both inline SVG from our own small layout functions. Everything in v3 still works.
Blog-size renders of each figure (1000 px wide, 1x, light and dark) are in `shots/diagrams/`.

## Flow diagrams (v3.1)

**(A) Swimlane sequence diagram.** Expand a flow in **Flows**: the diagram is the default view; **Steps** switches
to v3's rail. Lanes are files (or `file:Class` when one file holds two actors in a flow, e.g. `KVCache` in
`engine.py`), time runs down, hop numbers sit in the left gutter.

- **Call arrows**: solid = read in source or seen at runtime (the evidence shape before the label says which),
  dashed = inferred (dynamic dispatch, `opt.step()`), dotted = trace blind spot (`loss.backward()`; autograd runs in
  C++), with a short note under the arrow. A filled start dot marks where the flow begins.
- **Returns**: thin lines with an open chevron, carrying the data as a pill (`x, y (B, T) int64`, `loss scalar`).
  Data handed to the next call inside the same lane is a pill on that lane (`x (B, T, 768) bf16`).
- **Loop frames** from repeats: `LOOP × grad_accum micro-batches` (hops 2-6), `LOOP per new token, × max_tokens`.
  A repeat of one hop stays in its label (`Block.forward()  × 12`), as on the rail.
- **Activation bars** show which file is active (GPT.forward stays active across its two self-calls).
- Every arrow and data pill is a button: hover for the code preview, click to pin it (GitHub ↗ / Open in editor, as
  chips), Enter when focused. The preview gains a line naming the hop ("Hop 6 of 7 · loss.backward() · seen at
  runtime"), its description and any blind-spot note.
- Same hops, order, labels, anchors and evidence as the rail (checked in the headless tests).
- The panel's rail gains **View as diagram**: for a map flow it scrolls to the diagram and flashes it (a still ring
  under reduced motion); for a Tracer answer that is not a map flow (`engine2`) it opens the diagram in an overlay
  over the map, never over the panel (Escape closes).

**(C) Module graph** (Overview, after the first paragraph): files as boxes with their one-line role (the same
strings as the Modules headings), arrows weighted by the number of calls that cross between two files across the
map's flows (line weight 1.5 px per call, plus a count label), `ENTRY POINT` on `train.py`, a start dot where each
traced flow starts, and files in no traced flow shown faint (`checkpoint.py`). Hover an arrow for its calls; click it
to open the flow and highlight those calls; click a box to jump to its module.

**Content changes the diagrams forced** (a diagram asserts claims, so it caught them):
- The generate flow now has 6 hops, not 5: the loop calls `GPT.forward(nxt, cache)` once per new token
  (engine.py:56-57), which v3's rail left out; a "per new token" frame around `sample` alone would have said the model
  isn't called per token. `sample`'s anchor narrowed to engine.py:54-55.
- In the `engine2` answer, the `logits (1, P, 50304)` edge moved from after `GPT.forward` to after the attention hop:
  logits exist only after every layer has run, and in v3's position they read as flowing into `KVCache.append`.
- `loss.backward()` gained its blind-spot note, on the rail too.

### Layout rules (for T7's renderer to copy)

Both figures are `layout(data, width) -> plain geometry`, then `render(geometry) -> SVG string`
(`layoutSeq` / `renderSeq`, `layoutGraph` / `renderGraph` in `index.html`). No DOM measuring: text width is
estimated as characters x font size x 0.6 (mono) or 0.56 (sans, deliberately generous), so the same input gives
the same picture anywhere, including a Python port.

Input per hop: `fn` (the label everywhere), `a` (anchor), `ev`, `d`, `from` (caller lane; `null` = start), `to`
(callee lane), optional `edge [name, shape]`, `loop` (id into the trace's `loops` labels), `blind` (note),
`edgeAfterLoop` (the edge row closes the loop frame first), `tag`.

Sequence diagram:
1. Lanes in order of first appearance in the hops. Lane header = name (mono) + role (from the Modules section).
2. Each gap between neighbouring lanes is as wide as the widest thing it must hold: both half-headers; a call label
   that starts there (labels sit on the caller's side, left-aligned after the activation bar, rightward calls; mirror
   for leftward); a self-call's loop + label (right of its lane); a return's pill (on the callee's side); half of a
   lane pill; the loop tag of a frame whose leftmost lane is on the gap's left. Extra width is shared evenly between
   gaps; if the width is short, the SVG scales down instead (viewBox).
3. One row per call (label above the line, anchor below, note lines below that); one row per return or lane pill.
   Where a hop's data goes: to the lane of whoever acts next (`ret` arrow), or, if that is the same lane, it stays as a
   pill on the lane. Calls start activation bars; a return closes the callee's bar; a call with no return closes
   after a short tail unless the next hop is made from that lane.
4. A loop opens a frame with its own head row (only lifelines cross it); the tag goes in the first lifeline-free
   interval of that row (reserved in step 2), with an opaque background only as a fallback.
5. Notes wrap inside the gap beside the caller, so no text runs across another lane's lifeline. All text has a
   background-coloured halo as a safety net.
6. The key lists only the line styles and evidence shapes the diagram uses.

Module graph:
1. Edges = calls between different files across the map's flows (self-calls and starts excluded); weight = count.
2. Layers by longest path from the files nothing calls (left to right). The tallest layer stacks top-down; others order
   by the barycentre of their neighbours (ties: first appearance) and each box centres on the **median** of the ports
   its lines use, so a source with an odd number of targets runs straight into the middle one.
3. Fan-out is stub -> vertical bus -> horizontal drops into each target's left side (one bus per source, offset
   22 px). A target with several incoming lines gets one port per line, ordered like their sources, so lines never
   share a segment. Count labels sit right-aligned just before the arrowhead: above the line, except the last of
   several ports, below.
4. Start stubs share one left x; files in no flow sit faint below the tallest layer.

## Hard checks the headless tests run on every diagram
Call arrows = hops; rail and diagram agree on labels, order, anchors and evidence; line style matches evidence /
blind spot; every rail edge is drawn; loop hops inside their frame and the others outside; no text bounding box
touches an arrow line (a pill's own return line excepted), no two labels overlap; only safe characters (no tofu);
lane roles = Modules headings; graph counts = the flows' cross-file calls, weight ordered like counts, no crossing
lines, one entry point; previews open on hover / click / Enter with the right anchor and links; View as diagram
scrolls and highlights; overlay opens and closes without changing the map; nothing fetched.

## The visual system as built

- **Theme**: warm editorial. Light: canvas `#F8F7F4`, paper `#FFFFFF`, ink `#24272B`, muted `#66717D`, borders
  `#E8E5DF`. Dark is its own charcoal palette, not an inversion: canvas `#171A20`, surface `#1F232A`, ink `#F0F1F3`,
  muted `#A5AAB5`, borders `#323741`. These are the author's sample values plus a few in-between tones (sunken, faint, a
  second border).
- **Colour roles**
  - **amber** (`#B8862A`, highlight `#F5E7C9`): the reader's selections and notes: discussed passages on the map,
    the anchored quote, spans a follow-up branched from, note markers, the My notes switch, the Notes tab.
  - **indigo** (`#5267B2` / dark `#9FAEF1`): AI-generated content and discussions: the rule beside every answer,
    the name of the agent that wrote it, discussion count pills in the margin, section counts, the working halo.
  - **green** (`#28835C`): backed by source: evidence marks, the highlighted lines in a code preview, a hovered chip.
  - **honey brown** (`#8F5A24` / dark `#CD8C4E`): brand and primary actions: the logo dot, the Ask button, the
    active tab and contents item, the focus ring.
- **Evidence labels** (designer's adjustment 1): never amber or indigo. Each label is a SHAPE, readable without
  colour, in a green-to-grey range, and the label shows on hover:
  read in source = solid dot · asserted by a test = solid square · seen at runtime = dot in a ring · docs = triangle
  · inferred = hollow ring · searched, not found = dotted ring · general knowledge = hollow diamond.
  The Checker's ✓ stays a separate mark after the chip; "not supported" stays a quiet red flag.
- **Answers name their author** (adjustment 2): each answer starts with the agent's avatar and name in indigo
  ("🔦 Investigator · answer", "🧵 Tracer · routed by 🧭 Guide as a flow question"); no generic "Honeyguide".
- **Type**: Inter for UI and body, JetBrains Mono for code, each with system fallbacks (`-apple-system`, `ui-monospace`).
  This file does not fetch or embed fonts, so it renders in the fallbacks unless Inter and JetBrains Mono are
  installed. **The real app will bundle both font files locally** (licences checked when bundling). Scale: title
  30px/700, section 20px/600, body 15px/400 at 1.7, controls 13px/500, code refs 11-12px mono. Reading column: 696px
  of text (712px with padding), the same width with the panel open or closed.
- **Shape and motion**: 8px spacing, 24-40px between sections, quiet 1px borders, a light lift only on floating
  things (preview, toolbar, tooltip); radii 6px chips, 8px controls, 12px panels and the preview card; 16px icons at
  1.75px stroke; transitions 120-180ms.
- **Reduced motion** (`prefers-reduced-motion: reduce`, or `&motion=reduce` in the URL): nothing animates. A working
  avatar keeps a still indigo ring and a small "…" badge; busy margin pills stop pulsing and get a dashed ring; the
  loading bars are still.
- **Focus**: every control shows a 2px honey-brown ring on keyboard focus (`:focus-visible`).

## Source links (new)

Hover an anchor chip for a code preview; click to pin it. The preview header has **GitHub ↗** (a permalink pinned
to the commit the map was checked at, `blob/<full sha>/<path>#Lx-Ly`, never a branch) and **Open in editor**. In
this mockup neither is followed: the GitHub link has no `href`, and both show a toast saying what would open. When
the map's commit is not on the remote, GitHub is replaced by a quiet "GitHub · not pushed"; hover it for the reason
(state `unpushed`). A hover preview now stays open while the pointer moves onto it, so the links can be reached
without pinning.

## Memory state (new)

Under the title: "Up to date at `3f9c1e2` · 20 claims, every anchor resolved" (hover for what that means). After a
refresh (state `refreshed`), a calm summary reads "Refreshed since your last visit · updated from `a1b2c3d` to
`3f9c1e2`, 4 commits", with **12 moved · 3 re-checked · 1 retired · 2 new sections** (click a count to jump to an
example; × dismisses the summary) and the Checker shown re-checking. On the map:

- **stale, re-checking**: the claim's text greys, its evidence mark is withdrawn and replaced by a dashed
  "stale, re-checking" tag (hover: which lines changed, in which commit; not served as fact or given to agents
  until the Checker re-reads them). The header counts them ("22 claims, 2 stale").
- **retired**: struck through, tagged "retired", with its reason on the line below; its chip is struck and opens nothing.
- **re-checked**: a small ↻ after the chip (hover: re-checked at which commit, still supported).
- **new sections**: tagged "new" at the right of the module heading.

## States (URL hash)

Add `#state=...` and, optionally, `&theme=light|dark` and `&motion=reduce`. Without `theme`, the page follows the
system setting; the toggle at the bottom of the sidebar switches it. With a `state`, transitions are off for screenshots.

| Hash | Shows | Screenshots (`shots/`) |
|---|---|---|
| (none) or `#state=default` | The map at rest: margin markers, section counts, one note, "Up to date at 3f9c1e2" | `default-{light,dark}.png` |
| `#state=select` | The floating toolbar (Ask, Annotate, Copy) over a selected passage | `select-*` |
| `#state=answer` | Panel open on a checked Investigator answer: check marks, one "not supported" flag with its reason, one general-knowledge claim | `answer-*` |
| `#state=branch` | Two follow-ups branched from words in that answer: tree, marked spans, breadcrumbs, a pinned preview (with its links) | `branch-*` |
| `#state=path` | A follow-up routed by the Guide to the Tracer; its path view in the panel | `path-*` |
| `#state=working` | Agents at work in the panel: Checker part-way, Investigator reading, "Also at work" | `working-*` |
| `#state=working&motion=reduce` | The same under reduced motion: still avatars with the working badge, dashed pills | `working-reduced-*` |
| `#state=busy` | The same work with the panel closed: the single "4 at work" indicator | `busy-*` |
| `#state=notes` | The Notes tab: a note on the map, a saved answer (with its author), the seeded note | `notes-*` |
| `#state=navigator` | The Discussions tab: threads grouped by section, agents at work | `navigator-*` |
| `#state=preview` | A pinned code preview with **GitHub ↗** and **Open in editor**; the permalink shown on hover | `preview-*` |
| `#state=unpushed` | The map at a local commit `9e4d7a0`: "local commit, not on GitHub yet"; the preview has no GitHub link, and its reason is shown | `unpushed-*` |
| `#state=refreshed` | The refresh summary and a stale claim in the Overview | `refreshed-*` |
| `#state=refreshed&at=modules` | Scrolled to Modules: a stale claim, re-checked marks, the retired claim and its reason, the two new sections | `refreshed-modules-*` |
| `#state=flow-train` | v3.1: the training-step flow expanded as a swimlane diagram | `flow-train-*` |
| `#state=flow-generate` | v3.1: the generate flow as a swimlane diagram (6 hops, per-token loop) | `flow-generate-*` |
| `#state=overview-graph` | v3.1: the module graph, hovering train.py -> model.py (its 2 calls listed) | `overview-graph-*` |
| `#state=flow-hover` | v3.1: an arrow's code preview pinned (`loss.backward()`: hop context, blind-spot note, links) | `flow-hover-*` |
| `#state=flow-panel` | v3.1: a Tracer answer in the panel; **View as diagram** has scrolled the map to the diagram and flashed it (the diagram re-laid out for the narrower space) | `flow-panel-*` |
| `#state=path-diagram` | v3.1: the `engine2` Tracer answer (not a map flow) as a diagram overlay | `path-diagram-*` |
| `#state=fig&fig=step\|gen\|engine2\|graph&w=1000` | v3.1: the figure alone, for blog-size PNGs (window = the figure's size, title gives it) | `diagrams/*` |

## Try it live

- Select text in the map and choose **Ask**. The Guide routes it (about 0.7 s), the Investigator "reads" (about
  2 s), the answer appears with its claims plain, then the Checker checks them one by one.
- Select words inside that answer and choose **Ask** again: the follow-up nests under the answer, marked at the
  words you chose. Ask something that starts "What happens when …" to get the Tracer and a path view.
- **Annotate** writes a note; **Save as note** under an answer saves the whole answer. The **My notes** switch hides
  note markers. Close the panel while an answer is being worked on to see the top indicator.
- Hover or click a chip for its code preview and links.

Answers are canned per topic, so a question about one thing can get a sample answer about a neighbouring one.

## Re-rendering the screenshots

Headless Chrome, 1440x900 at 2x, under a timeout (a hung Chrome once blocked a run for 15 minutes; macOS has no
GNU `timeout`, so use perl's alarm):

    perl -e 'alarm 60; exec @ARGV' "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
      --hide-scrollbars --window-size=1440,900 --force-device-scale-factor=2 --virtual-time-budget=1500 \
      --screenshot=mockup/shots/preview-dark.png "file://$PWD/mockup/index.html#state=preview&theme=dark"

The page scrolls inside its main column, not the window, because headless Chrome renders a blank screenshot
when the window itself is scrolled.

## Choices for the author to confirm (from the v3.1 writer, 2026-11-15)
1. Solid arrow = read in source OR seen at runtime; the evidence shape before the label says which (alternative: a fourth line style).
2. The generate flow is 6 hops, not v3's 5: the per-token `GPT.forward(nxt, cache)` was missing; `sample` narrowed to engine.py:54-55.
3. engine2: the `logits` edge moved after the attention hop, outside the per-layer loop (it read as flowing into `KVCache.append`).
4. A one-hop repeat stays in its label (`Block.forward() × 12`), no frame.
5. Return arrows are thin with an open chevron (dashed already means inferred).
6. Entry/end tags aren't repeated on the diagram; the start dot and last row show them.
7. With the panel open the diagram scales to ~0.8 (text ~10px); see shots/flow-panel-*.png.
8. Graph start labels use hop labels; only train.py gets ENTRY POINT.
9. View as diagram and graph clicks jump instantly.
Designer's note: in the module graph, the train.py -> model.py and engine.py -> model.py lines arrive close together with two "2 calls" labels, so it's unclear which label belongs to which line. Fix in T7.4.
