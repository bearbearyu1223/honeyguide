# Swapping the agent emoji for the avatars

This is the mechanical swap of today's emoji-in-a-tinted-circle (`AG` and `avHTML` in `page.js`, the `.av` rules in
`page.css`) for the honey-drop avatars in this folder. The line numbers below are from the 2026-11-15 working tree.
T7.4 is editing those files, so find each spot by its code, not its number.

## 1. Files to bring in

| From `assets/avatars/` | To | Notes |
|---|---|---|
| `avatars.css` | append to `page.css`, or serve beside it and `<link>` it from `index.html` | self-contained: every class starts with `hg-av` |
| `hg-avatars.js` | load before `page.js`, or paste its `HG_AV` and `hgAv` at the top of `page.js` | generated; don't edit by hand |

The page has to own copies, because `assets/` is not served. After changing a design, regenerate the files with
`python3 assets/avatars/tools/build_avatars.py` (SVGs and `hg-avatars.js`) and
`sh assets/avatars/tools/render_pngs.sh` (PNGs, frames, GIF and APNG), then copy them over again.

`hgAv(agent, state, size)` returns one inline `<svg>` (about 3 KB, no ids, `aria-hidden`), so any number can share
a page.
- **state** is `idle | working | done | failed | waiting`. Add ` static` for an avatar that must never move,
  e.g. `"idle static"`.
- **size** sets the `width`/`height` attributes and adds a tuning class `hg-av-<size>`. The tuning classes exist
  for 20, 22, 24, 28, 40 and 96; small sizes get a thicker outline and lose the glints.

## 2. avHTML: keep the `.av` wrapper, swap its contents

```js
const AV_STATE = { true: "working", false: "idle" };
const avHTML = (ag, working, tip, size = 28, state) =>
  `<span class="av a-${esc(ag)}${working ? " working" : ""}"${tip ? ` data-tip="${esc(tip)}"` : ""} aria-hidden="true">`
  + hgAv(AG[ag] ? ag : "guide", state || AV_STATE[!!working], size) + `</span>`;
```

Keep the wrapper. It carries `data-tip`, the existing `.av.working` hook, and the reduced-motion "…" badge
(`.rm .av.working::after`), so all of those keep working unchanged.

In `page.css`:
- **Delete** `.av .face`, the five `.av.working.a-* .face` rules, and the `needle`, `unfold`, `sweep`, `spool` and
  `tick` keyframes. The creature now does that job.
- **Delete** the `--avbg` tints: the body carries the agent's tint. Set `.av{background:none}`.
- **Size rules:** change `.av` (and the `.elsewhere`, `.rf-w`, `.top .mini`, `.by` variants) from emoji font sizes
  to the box size only, e.g. `.by .av{width:28px;height:28px}`. Pass the same number as `size` to `avHTML` so the
  tuning class matches.
- **Halo, your call:** the `halo` animation on `.av.working` is a pulsing box-shadow. The creature already shows the
  work, so I would remove it. If kept, it should become a ring that changes opacity, as the brief allows only
  transform/opacity motion.

## 3. Which size and which state, per call site

| Where (today's code) | Size now → new | State |
|---|---|---|
| Answer header `.by` in `nodeHTML` (`avHTML(r.agent, false)`) | 20 → **28** | `idle`. `done` only on the first render after the answer arrives (see the note below) |
| Panel work row `workHTML` / `.work` (`avHTML(w.agent, true)`) | 28 → **40** | `working` |
| Thread "is working on it" (`avHTML(q.agent…, true)`) | 28 → **40** | `working` |
| Waiting for the Guide (`avHTML("guide", false)` before "Waiting for the 🧭 Guide") | 28 → 28 | **`waiting`** (sleepy eyes, dream bubble) |
| Failed reply (`q.status === "failed"`, has no avatar today) | (none) → **20** | **`failed`**: add `avHTML(q.agent || "investigator", false, "", 20, "failed")` before "Couldn't answer" |
| Top bar "N at work" `.top .mini` | 24 → 24 | `working` |
| "Also at work" `.elsewhere` | 22 → 22 | `working` |
| Refresh row `.rf-w` (Checker re-checking) | 22 → 22 | `working` |
| Navigator thread rows (`busy.map(b => avHTML(b.agent, true))`) | 28 → 24 | `working` |

**`done` replays on every re-render.** It is a one-shot animation, so the hop and sparkle play again whenever the
node is rebuilt, and the panel re-renders on each poll. Two ways to handle it:
- Remember shown ids, e.g. `UI.hopped = new Set()`, and use `done` only for a response id not yet in the set.
- Or always render `idle` and skip `done` entirely.

The sheet shows `done` with happy eyes and a grin that stay after the hop, so a `done` that is never replayed still
reads as content.

## 4. Reduced motion and dark: nothing to wire

- **Reduced motion:** `avatars.css` stops all avatar motion under `@media (prefers-reduced-motion: reduce)` and under
  an `.rm` ancestor, the page's existing switch (`setMotion` toggles `.rm` on `<html>`). Each state gets a still
  pose:
  - working: the Guide's flag raised, the Investigator's lens over an eye, the Checker's badge pressed down, the map
    open.
  - done: sparkles shown.
  - waiting: dream bubble shown.

  The page's own `.rm *{animation:none!important}` already agrees with this. The `.rm .av.working` ring and "…"
  badge stay as they are.
- **Dark:** keyed off `:root[data-theme="dark"]`, which `setTheme` already sets. In dark the bodies are dimmer and
  warmer, the outline turns honey `#C98348`, and the trail dots turn `#E2C25C`.

## 5. The emoji inside text strings

My proposal: **where the string is HTML, use a 20px avatar with `idle static`. Where the string is plain text or an
attribute, drop the emoji and keep the name.** In running prose a moving creature competes with the reading, which
is why these avatars are `static`. In headers and work rows they stay animated.

| Line (code) | Kind | Proposal |
|---|---|---|
| `AG` map and `agFull` | helper | `AG[a][0]` is no longer needed. Split `agFull` into `agHTML(a)` = `hgAv(a, "idle static", 20) + " " + name` for HTML, and `agName(a)` for text |
| welcome list "The 🗺️ Cartographer reads the code…" | HTML | `agHTML("cartographer")` |
| `#sub` "Mapped by the 🗺️ Cartographer · …" | `textContent` | name only ("Mapped by the Cartographer · …"), or switch to `innerHTML` with `agHTML` if Han wants the creature in the subtitle |
| `#dgovs` "🧵 Tracer answer, as a diagram" | `textContent` | name only |
| flow header meta `<span class="em">🧵</span>Tracer · N hops` | HTML | `hgAv("tracer", "idle static", 20)` in place of the `em` span |
| "N stale claims waiting for the ✅ Checker" | HTML | `agHTML("checker")` |
| "Not checked yet · … waiting for the ✅ Checker" | HTML | `agHTML("checker")` |
| `checkHTML` result `<span class="em">✅</span>N of M supported` | HTML, a **result mark**, not the agent | keep as it is. The visual system says the Checker's ✓ stays a separate mark |
| "· routed by 🧭 Guide as a flow question" | HTML | `agHTML("guide")` |
| "Waiting for the 🧭 Guide. Your Claude Code session…" | HTML | the avatar before it is already the `waiting` Guide, so drop the emoji from the sentence: "Waiting for the Guide." |
| thread meta `agFull(r.agent)` / "🧭 Guide" · working · N claims | HTML | `agHTML` |
| empty-panel "The 🧭 Guide sends it to the 🔦 Investigator, or to the 🧵 Tracer…" | HTML | `agHTML` for each |
| navigator row emoji list `ags.map(a => AG[a][0])` | HTML | `ags.map(a => hgAv(a, "idle static", 20))` |
| `"What happens when …" questions go to the 🧵 Tracer.` | HTML | `agHTML("tracer")` |
| notes: `Saved answer · ${esc(agFull(…))}`, "written by …" | HTML, but escaped | `agHTML` without `esc()`. The name inside is fixed, not user data |
| any `data-tip` / `title` / `aria-label` text | attribute | name only |

Copy and paste are fine: the SVGs are `aria-hidden` and contain no text, so copied answers read "Investigator ·
answer".

## 6. Check after the swap

- `#state=working`, `#state=answer`, `#state=path` and `#state=navigator`, light and dark.
- `#state=working&motion=reduce`: still poses plus the ring and "…" badge.
- A 20px avatar in prose has to sit on the text baseline. `.inl .hg-av{vertical-align:-4px}` worked in
  `sheet.html` at 15px/1.7. Tune it for the page's 15px body.
