# Honeyguide map page: static UX mockup

`index.html` is one self-contained file (inline CSS and JS, no network, no build step). Everything in it is
SAMPLE content: a made-up map of a small GPT training repo called `tinytrain`. Open it in any browser:

    open mockup/index.html

## States (URL hash)

Add `#state=...` and, optionally, `&theme=light|dark`. Without `theme`, the page follows the system setting
(`prefers-color-scheme`); the toggle at the bottom of the sidebar switches it.

| Hash | Shows | Screenshots |
|---|---|---|
| (none) or `#state=default` | The map at rest: contents, evidence dots, anchor chips, two closed threads (margin dots) | `shots/default-{light,dark}.png` |
| `#state=thread` | A thread open in place: a checked answer from the Investigator (one claim flagged "not supported") and a follow-up asked from a highlight inside the answer | `shots/thread-{light,dark}.png` |
| `#state=path` | The Tracer's path for "What happens in one training step?", with one hop's code open | `shots/path-{light,dark}.png` |
| `#state=working` | Agents at work: the status strip with all five avatars, and an answer still being checked (claims plain, no dots yet) | `shots/working-{light,dark}.png` |
| `#state=select` | The Ask / Note popover over a highlight (an extra state) | `shots/select-{light,dark}.png` |

Example: `open "mockup/index.html#state=thread&theme=dark"`.

## Try it live

- Highlight any text in the map, then choose **Ask**. A thread opens in place; type a question (or leave it
  empty) and press Enter. The answer arrives after about 2 s with plain claims; about 2 s later the Checker
  adds each claim's evidence dot, and one claim gets a "not supported" flag.
- Highlight text inside an answer and choose **Ask** again to ask a follow-up in the same thread.
- Choose **Note** instead to keep a note. It stays in this tab (in memory only), lists under Notes, and starts
  no agent.
- Click an anchor chip (`train.py:12`) to open its code inline. Click a hop in a path to open its code.
- Hover a dot, a flag or an avatar for its label.
- Press **d** to play a scripted 10-second sequence in which all five agents work (🧭 Guide, 🗺️ Cartographer,
  🔦 Investigator, 🧵 Tracer, ✅ Checker).

## Re-rendering the screenshots

Headless Chrome, 1440x900 at 2x:

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars \
      --window-size=1440,900 --force-device-scale-factor=2 --virtual-time-budget=1500 \
      --screenshot=mockup/shots/thread-dark.png "file://$PWD/mockup/index.html#state=thread&theme=dark"

The page scrolls inside its main column, not the window, because headless Chrome renders a blank screenshot
when the window itself is scrolled.
