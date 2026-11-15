# Honeyguide map page: static mockup (v3)

`index.html` is one self-contained file (inline CSS and JS, no network, no build step, no web fonts fetched).
Everything in it is SAMPLE content: a made-up map of a small GPT training repo called `tinytrain`, with canned
answers. Open it in any browser:

    open mockup/index.html

v3 is v2's interaction model, unchanged, in Han's visual system (`feedback/2026-11-15-han-visual-design-recommendations.html`;
plan §3b "Visual system"), plus two additions agreed after v2 started: **source links** in the code preview and
the **memory state** (plan §3b "Source links", "Memory and refresh"). v2's screenshots are in `shots/v2/`, v1's in
`shots/v1/` (v1 = commit 625a1ae, v2 = 7e16f77).

## The visual system as built

- **Theme**: warm editorial. Light: canvas `#F8F7F4`, paper `#FFFFFF`, ink `#24272B`, muted `#66717D`, borders
  `#E8E5DF`. Dark is its own charcoal palette, not an inversion: canvas `#171A20`, surface `#1F232A`, ink `#F0F1F3`,
  muted `#A5AAB5`, borders `#323741`. These are Han's sample values plus a few in-between tones (sunken, faint, a
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
