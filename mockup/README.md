# Honeyguide map page: static UX mockup (v2)

`index.html` is one self-contained file (inline CSS and JS, no network, no build step). Everything in it is
SAMPLE content: a made-up map of a small GPT training repo called `tinytrain`, with canned answers. Open it in
any browser:

    open mockup/index.html

v2 merges Han's UX recommendations (`feedback/2026-11-15-han-ux-recommendations.html`) with the plan (§3b,
"UX (v2, agreed 2026-11-15)"). v1 (commit 625a1ae) kept threads inline in the map and showed agents in a bottom
strip; its screenshots are in `shots/v1/`.

## What the page has

- **The map** (centre), same width with the panel open or closed. Contents on the left, with a count of
  discussions beside each section, a **My notes** layer switch, and the evidence legend.
- **Discussion markers** in the right margin: a small numbered pill per discussed passage (the number is how
  many questions it holds; it breathes while an agent works on it), a hollow square per note.
- **Selection toolbar**: select any text, in the map or in an answer, and choose **Ask**, **Annotate** or **Copy**.
- **Discussion panel** (right, on demand) with three tabs:
  - **Thread**: breadcrumbs, the anchored passage ("Show in map"), and the thread as a collapsible tree. A
    follow-up asked from words selected inside an answer stores its parent answer and the span; the span stays
    marked in the parent answer and the follow-up nests under it, so threads branch. The composer at the bottom
    offers quick prompts (Explain this, Show an example, Find the implementation) when there is a selection.
  - **Discussions**: the navigator, grouped by section, with the agents at work; click one to open it and jump
    to its passage.
  - **Notes**: your notes, a separate layer: notes on the map, notes on answers, and answers saved with
    **Save as note**. Nothing you write or save changes the map.
- **Agents**: animated emoji avatars sit in the panel beside the question being worked on, each with a one-line
  status ("Investigator reading engine.py 45–58 …"); work on other threads is listed in a small "Also at work"
  strip. With the panel closed, the one control at the top right turns into an "N at work" indicator with the
  avatars. There is no bottom strip.
- **Provenance**: each claim has its evidence dot and anchor chip (hover a chip for a code preview; click to
  pin it). In answers, the Checker adds a separate small check mark to each claim it supports, or a quiet
  "not supported" flag (hover for its reason). Claims labelled **general knowledge (not from this repo)** have
  a hollow diamond and a dashed tag, and the Checker skips them.
- **Routing**: questions that read "what happens when …" go to the 🧵 Tracer, and its path view renders in the
  panel. Every answer names the agent that wrote it ("Tracer · routed by Guide as a flow question").

## States (URL hash)

Add `#state=...` and, optionally, `&theme=light|dark`. Without `theme`, the page follows the system setting;
the toggle at the bottom of the sidebar switches it. With a `state`, transitions are turned off for screenshots.

| Hash | Shows | Screenshots |
|---|---|---|
| (none) or `#state=default` | The map at rest, panel closed: margin markers, section counts, one note, "Discussions 3" at the top right | `shots/default-{light,dark}.png` |
| `#state=select` | The floating toolbar (Ask, Annotate, Copy) over a selected passage | `shots/select-{light,dark}.png` |
| `#state=answer` | Panel open on a checked Investigator answer: check marks, one "not supported" flag with its reason shown, one general-knowledge claim | `shots/answer-{light,dark}.png` |
| `#state=branch` | Two follow-ups branched from words in that answer: the tree (one branch open, one collapsed), the marked spans, breadcrumbs, a pinned code preview | `shots/branch-{light,dark}.png` |
| `#state=path` | A follow-up "What happens when generate is called a second time?" routed by the Guide to the Tracer; its path view in the panel (parent answer collapsed) | `shots/path-{light,dark}.png` |
| `#state=working` | Agents at work in the panel: the Checker part-way through an answer, the Investigator reading for a follow-up, and "Also at work" (Cartographer, Tracer) | `shots/working-{light,dark}.png` |
| `#state=busy` | The same work with the panel closed: the single "4 at work" indicator at the top right, busy markers | `shots/busy-{light,dark}.png` |
| `#state=notes` | The Notes tab: a note on the map, a saved answer, the seeded note; note markers in the margin | `shots/notes-{light,dark}.png` |
| `#state=navigator` | The Discussions tab: threads grouped by section, agents at work, the Cartographer's map work | `shots/navigator-{light,dark}.png` |

Example: `open "mockup/index.html#state=branch&theme=dark"`.

## Try it live

- Select text in the map and choose **Ask**. Type a question or pick a quick prompt. The Guide routes it (about
  0.7 s), the Investigator "reads" (about 2 s), the answer appears with its claims plain, then the Checker
  checks them one by one: dots and check marks arrive, one claim may be flagged.
- Select words inside that answer and choose **Ask** again: the follow-up nests under the answer, marked at the
  words you chose. Do it twice for two branches. Collapse a branch with its caret; jump with the breadcrumbs.
- Ask something that starts "What happens when …" to get the Tracer and a path view.
- **Annotate** writes a note (map or answer); **Save as note** under an answer saves the whole answer. Notes
  appear in the Notes tab; the **My notes** switch hides their markers.
- Close the panel while an answer is being worked on to see the top indicator.

Answers are canned per topic, so a question about one thing can get a sample answer about a neighbouring one.

## Re-rendering the screenshots

Headless Chrome, 1440x900 at 2x:

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars \
      --window-size=1440,900 --force-device-scale-factor=2 --virtual-time-budget=1500 \
      --screenshot=mockup/shots/branch-dark.png "file://$PWD/mockup/index.html#state=branch&theme=dark"

The page scrolls inside its main column, not the window, because headless Chrome renders a blank screenshot
when the window itself is scrolled.
