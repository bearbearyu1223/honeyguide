# Honeyguide map page, UX v4 (T7.17 + T7.18)

Han's asks, in his words: the component diagram "is very small, and not readable ... allow zoom in zoom out"; "the
diagram like this is really hard to read and navigate"; a repo overview "by providing the detailed repo info, like
link, programming language, authors, stars"; "the font and layout can be designed better, so it is easy to understand
and find the section; the UX should give people a clean and professional feel"; "leverage the UX design of NotebookLM
from Google, for the feel and the theme".

What we borrow from NotebookLM is its **feel**, not its look: three calm areas on a tonal canvas, rounded surfaces,
generous whitespace, a clear type hierarchy, quiet chrome, citations as compact chips that show their passage, and
a mind map you can click into a grounded chat. What stays Honeyguide's: Honey (logo and the Guide's avatar), the
honey/amber palette and its four colour roles, Inter + JetBrains Mono (system fallbacks; Google Sans is not ours).

## 1. Layout map

```
┌──────────────┬───────────────────────────────────────────┬─────────────────┐
│ CONTENTS     │  MAP (reading column of cards)            │ DISCUSSION      │
│ (rail ⇄ 56px)│                                           │ (unchanged)     │
│ Honey  Hgd ◧ │  ┌─ Repo card ───────────────────────┐    │ Thread · Disc.  │
│ nanochat@sha │  │ nanochat  ↗ github.com/karpathy/… │    │ · Notes         │
│ [ Find… ⌕ ]  │  │ description (README)              │    │                 │
│              │  │ ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇░░ Python 81% …    │    │                 │
│ ▾ Overview   │  │ MIT · Karpathy +4 · ★ n/a         │    │                 │
│   Purpose ●  │  │ created · last commit · mapped at │    │                 │
│   Who it's…  │  │ ✓ Up to date at 92d63d4 · claims  │    │                 │
│   …          │  └───────────────────────────────────┘    │                 │
│   Component  │  OVERVIEW ───────────── (sticky)          │                 │
│   map        │  ┌ Purpose ──────────────────────────┐    │                 │
│ ▾ Modules    │  │ 66-75 character lines             │    │                 │
│   gpt.py …   │  └───────────────────────────────────┘    │                 │
│ ▾ Flows      │  ┌ Component map  [−][+][Fit][⤢] ────┐    │                 │
│   …          │  │ Entry points │ Stages │ Leaves     │    │                 │
│ Needs a look │  │ (show all 27 calls)   [focus card] │    │                 │
│ My notes ◯   │  └───────────────────────────────────┘    │                 │
│ Evidence ▸   │  MODULES ─────────── (sticky)             │                 │
│ ◐ Dark       │  ┌ module card ┐ ┌ module card ┐ …        │                 │
└──────────────┴───────────────────────────────────────────┴─────────────────┘
```

- **Left, contents** (264 px, collapses to a 56 px rail as before): brand, the repo line, a **Find** box, then the
  outline: each section with its sub-sections (the Overview's topics and the Component map, each module by its short
  name, each flow). **Scroll-spy** marks the section and the sub-section you are reading. Below: Needs a look, My notes,
  the evidence key (folded, one click), theme. The side and the panel are tonal surfaces inset 8 px from the window
  edge with 16 px radii, like NotebookLM's panels; the canvas shows between them.
- **Centre, the map**: a column of **cards** on the canvas. The repo card first, then each section under a **sticky
  section header** (small caps label + count), each Overview topic a card, the Component map its own wide card, each
  module a card, each flow a card. Cards: 16 px radius, 1 px hairline, no shadow at rest.
- **Right, discussion panel**: behaviour unchanged (Thread / Discussions / Notes, composer, resize grip); it gains the
  same inset and radius. The diagram overlay and full-screen views never sit under it.

## 2. Type scale (Inter; JetBrains Mono for code)

| role | size / line height / weight | where |
|---|---|---|
| Display | 28 / 1.2 / 700, -0.03em | repo name in the repo card (the page's only h1) |
| Section | 20 / 1.3 / 650 | sticky section header text (Overview, Modules, Flows) |
| Card title | 16 / 1.4 / 620 | topic cards, module titles, flow titles |
| Body | 16 / 1.65 / 400 | map prose, at most 35em per line (66-75 characters of running text) |
| Secondary | 14 / 1.55 / 400-500 | contents, facts, captions, panel body |
| Meta | 12 / 1.5 / 500-650 | labels (small caps 0.08em), chips (mono 12), counts |

Nothing on the page is set below 12 px, diagrams included at their fitted size (§5).

## 3. Spacing (8 px grid)

4 (hairline gaps inside chips) · 8 · 12 (rare: chip padding) · 16 · 24 · 32 · 48. Cards: 24 px padding (32 on the repo
card), 16 px apart; sections 48 px apart; the reading column 680 px (prose 35em inside it), figures break out to the
map area's width (560-1000 px) as before.

## 4. Colour tokens

The v3 tokens stay (warm editorial, light and a separate charcoal dark). v4 adds tonal layers:

| token | light | dark | use |
|---|---|---|---|
| `--canvas` | `#F4F2EE` | `#14161B` | behind everything |
| `--surface` | `#FFFFFF` | `#1D2027` | cards, side, panel |
| `--surface-2` | `#FAF8F5` | `#23272F` | sunken areas inside cards (facts, figure toolbars) |
| `--hair` | `#ECE8E1` | `#2E333C` | card borders, separators |
| `--tint-brand` | `#F6ECDF` | `#3A2B1E` | current contents item, selected chips |
| `--elev-1` | soft 1-3 px | darker | floating things only: preview, tooltip, toolbar, focus card, full screen bar |

Colour roles unchanged: **amber** = the reader (selections, notes), **indigo** = AI (answers, agent names, discussion
counts), **green** = backed by source (evidence shapes, cited lines, hovered chips and edges), **honey brown** = brand
and primary actions (logo, Ask, current contents item, focus ring, the graph's focused component). Language bar colours
are a fixed neutral-to-honey ramp (no GitHub linguist colours: they would add a fifth role).

## 5. Components

**Repo card** (`document.repo`, written by `honeyguide repo-info` at map time; the page fetches nothing):
name + link (normalised https), the README's description line, a language bar (top 5 + other, by lines of tracked
source) with a legend, licence (SPDX id guessed from the licence text, with its file), top contributors (names only,
never emails, by commit count), stars / forks / open issues / topics **with "as of <UTC date>"** when `gh` was signed in
(else one quiet line: "GitHub counts not fetched: gh is not signed in"), created (first commit), last commit, mapped at
`<short sha>`; then the memory line (up to date, claims) and the refresh notices. Facts in the card are **provenance-
labelled metadata, not claims**: each row says where it came from (git at a commit, or the GitHub API on a date).

**Contents rail**: section rows (14/600) with sub-rows (13/400, indented 12), a 2 px honey-brown bar on the current
row; discussion counts in indigo; Find filters rows by name and searches the map's text (matches listed with their
section, Enter steps through them, marks in the map are a quiet amber-free outline so they never read as notes).

**Cards**: Overview topic (label + prose), Module (title, file chips, entry tag, responsibility, design note, More,
Related, "Show in component map"), Flow (title, Tracer meta, caption, Diagram / Steps).

**Diagram viewer** (every diagram: component map, flow swimlanes, Tracer overlay): a quiet toolbar (−, zoom %, +,
Fit, Expand) in the figure's top-right; Cmd/Ctrl + scroll and trackpad pinch zoom at the pointer; drag to pan;
keys + / − / 0 when focus is in the figure; Expand opens full screen over everything (Esc closes). Fit never sets
text below 12 px: a figure wider than that allows pans instead of shrinking further.

**Component map** (replaces the module graph): layered top to bottom in three bands derived from the graph:
**Entry points** (nothing traced calls them), **Stages** (called and calling, by longest path), **Leaves** (call
nothing traced). Each edge has its own route (its own port at both ends, a smooth curve, through its own slot past
any band it skips): no shared bus lines. Stroke weight encodes the call count; the count shows on hover. Default
**Main paths** (every edge used by two or more flows, plus each component's most-used incoming edge), with **Show
all N calls**. **Focus**: click (or Enter on) a component: it, its callers and callees stay, the rest fades; a focus
card lists its calls in and out with code chips and has **Ask about this component** (opens the panel anchored to that
module, the question prefilled) and **Open its module**. Esc or a click on empty space resets. A component with
several files has a **+N files** toggle that expands the node to list them.

## 6. Kept as is

Selection → Ask / Annotate / Copy, notes layer, evidence marks, previews (hover, pin, GitHub / editor links), Needs a
look, refresh states, avatars and their motion rules, keyboard focus ring, reduced motion, the CSP (no inline style or
script; styles set through the CSSOM only), nothing fetched but the page and its API.
