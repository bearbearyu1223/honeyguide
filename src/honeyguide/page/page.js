/* Honeyguide map page (T7.3). Renders whatever the memory store holds, through the page server's /api/*
   (docs/design/agent-contract.md). The page never starts Claude: questions and notes are POSTed to the inbox and
   the Claude Code session's `honeyguide watch` picks them up.

   Offsets: annotations are DocumentAnchors in the server's plain-text coordinates (mapdoc.plain_text for the map,
   the answer's text for answer:<id>), counted in Unicode code points like Python's str. Every piece of rendered
   document text is a "leaf" element carrying data-o, the plain-text offset of its first displayed character, and
   showing exactly that slice of the plain text (backtick code runs show without their backticks; the offset skips
   the opening one). Selections map back through the leaves; overlays (marks, notes) wrap text inside leaves only,
   so the map's own text is never changed. */
"use strict";

/* ---------------------------------------------------------------- basics */
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);
const one = s => String(s || "").replace(/\s+/g, " ").trim();
const cpLen = s => { let n = 0; for (const _ of s) n++; return n; };
/* UTF-16 index of code point k in s */
const cpIdx = (s, k) => { let i = 0; while (k > 0 && i < s.length) { const c = s.charCodeAt(i); i += c >= 0xd800 && c < 0xdc00 ? 2 : 1; k--; } return i; };
const cpSlice = (s, a, b) => s.slice(cpIdx(s, a), cpIdx(s, b));
const short = sha => (sha || "").slice(0, 7);
const lines = (a, b) => (a === b ? `line ${a}` : `lines ${a}–${b}`);
const inlineCode = s => esc(s).replace(/`([^`\n]+)`/g, "<code>$1</code>");
const qt = s => String(s || "").replace(/`([^`\n]+)`/g, "$1");   /* a quoted selection, shown without backticks */
const plural = (n, w, ws) => `${n} ${n === 1 ? w : (ws || w + "s")}`;

const TOKEN = $('meta[name="honeyguide-token"]').content;
const REPO_ID = $('meta[name="honeyguide-repo"]').content;
/* repo ids are host__owner__name__<root hash> (repoid.make_id); show owner/name */
const REPO_NAME = (() => { const p = REPO_ID.split("__"); return p.length >= 4 ? p.slice(1, -1).join("/") : p.length > 1 ? p.slice(0, -1).join("/") : REPO_ID; })();
const MAIN = $("#main"), COL = $("#col"), PBODY = $("#pbody");
const store = {
  get(k) { try { return localStorage.getItem("honeyguide." + k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem("honeyguide." + k, v); } catch (e) { /* private mode */ } },
};

class ApiError extends Error { constructor(status, err) { super(err.message || "request failed"); this.status = status; this.code = err.code; } }
async function api(path, body) {
  const opts = { headers: { "X-Honeyguide-Token": TOKEN } };
  if (body !== undefined) { opts.method = "POST"; opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok || data.ok === false) throw new ApiError(r.status, data.error || { message: `HTTP ${r.status}` });
  return data;
}

/* ---------------------------------------------------------------- vocabulary */
const EV = {
  read_in_source: ["Read in source", ""],
  asserted_by_test: ["Asserted by a test", "a test in the repo asserts it"],
  docs: ["Docs", "from the repo's documentation"],
  seen_at_runtime: ["Seen at runtime", "in a runtime trace"],
  inferred: ["Inferred", "not stated in the code; reasoned from the cited lines"],
  searched_not_found: ["Searched, not found", "looked for it and found no match"],
  general_knowledge: ["General knowledge", "not from this repo; the Checker skips it"],
};
/* agents: their names, and their avatars from hg-avatars.js (hgAv). The Guide is drawn as Honey, the mascot; its name
   stays "Guide" everywhere but the avatar's tip. */
const AG = { guide: "Guide", cartographer: "Cartographer", investigator: "Investigator", tracer: "Tracer", checker: "Checker" };
const HONEY = "Honey, the Guide";
const agName = a => AG[a] || a || "an agent";
/* an agent named in running HTML: its still 20px avatar, then its name (plain text and attributes use agName) */
const agHTML = a => AG[a] ? `<span class="agn"${a === "guide" ? ` data-tip="${HONEY}"` : ""}>${hgAv(a, "idle static", 20)}${AG[a]}</span>` : esc(agName(a));
const ICON = {
  ext: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M12 9.5v3a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3"/></svg>`,
  ed: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 5 2.5 8l3 3M10.5 5l3 3-3 3"/></svg>`,
  ok: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="m5.5 8 1.8 1.8L10.7 6.4"/></svg>`,
  info: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><circle cx="8" cy="8" r="6"/><path d="M8 7.2v3.6M8 5.2v.1"/></svg>`,
  rf: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M13 3.5v3h-3"/><path d="M12.6 6.5A5 5 0 1 0 13 9"/></svg>`,
  dg: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M4 2.5v11M12 2.5v11M4 6h6.5M10.5 4.5 12 6l-1.5 1.5M12 10H5.5M5.5 8.5 4 10l1.5 1.5"/></svg>`,
  msg: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round"><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/></svg>`,
};
const LOGO = `<span class="logo">${hgAv("guide", "idle", 40)}</span>`;   // Honey, the logo, on the empty page

/* ---------------------------------------------------------------- data */
const D = { state: null, map: null, threads: { questions: [], responses: [] }, notes: { notes: [] }, activity: { working: [], recent: [] } };
const UI = { hopped: new Set(), open: false, tab: "thread", cur: null, curNode: null, compose: null, closed: new Set(), openMods: new Set(), mapRev: null, pendingRev: null, dismissed: store.get("refreshDismissed") || "" };
let IDX = null;   // derived indexes, rebuilt by index()

function claimsById() {
  const m = new Map();
  for (const c of D.map?.claims || []) m.set(c.id, c);
  for (const r of D.threads.responses) for (const c of r.claims || []) m.set(c.id, c);
  return m;
}
/* Claim freshness, as memory.memory_state reads it (T7.5): a stale claim waits for the Checker (check unchecked)
   or failed its re-check (not_supported, stays stale, never served); a supported re-check makes it current again
   with rechecked_at. */
function lastRefreshAt() { const log = D.state?.refresh_log || []; return log.length ? log[log.length - 1].at : null; }
function claimState(c) {
  if (!c) return "missing";
  if (c.freshness === "retired") return "retired";
  if (c.freshness === "stale") return c.check === "not_supported" ? "stale_flagged" : "stale";
  const at = lastRefreshAt();
  if (c.rechecked_at && (!at || c.rechecked_at >= at)) return "rechecked";
  return "current";
}

/* ---------------------------------------------------------------- plain text and leaves */
/* a block's text pieces, as mapdoc.block_segments: its spans (if any), a module's design paragraph (T7.13b), then
   list items, then facts rows (T7.13); joined by one newline in the plain text */
function segsOf(block) {
  const segs = [];
  if (block.spans && block.spans.length) segs.push(block.spans);
  if (block.type === "module" && block.design && block.design.length) segs.push(block.design);
  for (const it of block.items || []) segs.push(it.spans || []);
  for (const r of (block.type === "facts" ? block.rows : block.facts) || []) segs.push(r.spans || []);
  return segs.length ? segs : [[]];
}
/* the map's plain text, exactly as mapdoc.plain_text builds it, with each block's [start, end) and the start of
   each of its segments */
function mapText(doc) {
  const parts = [], blocks = [];
  let pos = 0, first = true;
  for (const sec of doc.sections || []) {
    for (const piece of [sec.title || "", ...(sec.blocks || [])]) {
      if (!first) pos += 2;
      first = false;
      if (typeof piece === "string") { parts.push(piece); pos += cpLen(piece); continue; }
      const segs = [], texts = [];
      let p = pos;
      for (const seg of segsOf(piece)) {
        if (segs.length) p += 1;
        const t = seg.map(s => s.text || "").join("");
        segs.push(p); texts.push(t); p += cpLen(t);
      }
      const text = texts.join("\n");
      blocks.push({ id: piece.id, start: pos, end: pos + cpLen(text), sec, block: piece, segs });
      parts.push(text);
      pos += cpLen(text);
    }
  }
  return { text: parts.join("\n\n"), blocks };
}
/* leaves for one run of text starting at plain offset o; backtick code shows as <code> */
function leaves(text, o) {
  /* paragraph breaks (a blank line) render as a zero-height block leaf: offsets unchanged, 8px of space */
  if (/\n{2,}/.test(text)) {
    let html = "", pos = o;
    for (const part of text.split(/(\n{2,})/)) {
      if (!part) continue;
      html += /^\n+$/.test(part) ? `<span class="lf pbr" data-o="${pos}">${part}</span>` : leaves(part, pos);
      pos += cpLen(part);
    }
    return html;
  }
  let html = "", pos = o, last = 0;
  const re = /`([^`\n]+)`/g;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) { const t = text.slice(last, m.index); html += `<span class="lf" data-o="${pos}">${esc(t)}</span>`; pos += cpLen(t); }
    html += `<code class="lf" data-o="${pos + 1}">${esc(m[1])}</code>`;
    pos += cpLen(m[0]);
    last = m.index + m[0].length;
  }
  if (last < text.length) html += `<span class="lf" data-o="${pos}">${esc(text.slice(last))}</span>`;
  return html;
}
/* T7.15: a map claim the Checker marked not supported is quiet at rest (a faint dotted underline and the dashed
   "not supported" mark in place of its evidence shape) and shows its red flag and the Checker's note on hover or
   keyboard focus; the note is also its accessible description. Answers keep the inline "not supported" pill. */
const unsupported = c => !!c && c.check === "not_supported" && !["stale", "stale_flagged", "retired", "missing"].includes(claimState(c));
const NS_DEFAULT = "The Checker re-read the cited lines and they don't show all of this.";
const nsTip = c => `<b class="tflag">Not supported</b> · ${inlineCode(c.check_note || NS_DEFAULT)}`;
let NSN = 0;   // ids for the hidden descriptions, unique per render
/* spans (with claims) to HTML, offsets from o; ctx: "map" or "answer" */
function spansHTML(spans, o, ctx, byId) {
  let html = "", pos = o;
  for (const s of spans) {
    const t = s.text || "";
    if (s.claim) {
      const c = byId.get(s.claim);
      const st = claimState(c);
      const quiet = ctx === "map" && unsupported(c);
      const cls = ["claim", c?.evidence === "general_knowledge" ? "gk" : "", st.startsWith("stale") ? "stale" : "", st === "retired" ? "retired" : "",
        c?.check === "not_supported" && !st.startsWith("stale") ? "flagged" : "", quiet ? "quiet" : ""].filter(Boolean).join(" ");
      const ns = quiet ? `nsd-${++NSN}` : "";
      const a11y = quiet ? ` tabindex="0" aria-describedby="${ns}" data-tip="${esc(nsTip(c))}"` : "";
      html += `<span class="${cls}" data-claim="${esc(s.claim)}" data-st="${st}"${a11y}>${leaves(t, pos)}</span>${citeHTML(c, ctx)}`
        + (quiet ? `<span class="sr" id="${ns}">Not supported: ${esc(c.check_note || NS_DEFAULT)}</span>` : "");
    } else html += leaves(t, pos);
    pos += cpLen(t);
  }
  return html;
}

/* one segment of a map block: its spans, with a retired claim's reason moved under it so the sentence stays whole */
function segHTML(spans, o, byId) {
  const body = spansHTML(spans, o, "map", byId);
  const whys = [...body.matchAll(/<span class="rwhy-at" data-why="([^"]*)"><\/span>/g)].map(m => m[1]);
  return body.replace(/<span class="rwhy-at" data-why="[^"]*"><\/span>/g, "") + whys.map(w => `<span class="rwhy">Retired: ${w}.</span>`).join("");
}
/* the Overview's topic headings and the module facts' labels (mapdoc.TOPIC_TITLES, FACT_LABELS) */
const TOPICS = { purpose: "Purpose", users: "Who it's for", capabilities: "What it can do", commands: "Commands",
  "entry-points": "Entry points", components: "Components", "start-here": "Start here" };
const FACTS = { responsibility: "Responsibility", key_files: "Key files", key_symbols: "Key symbols", interfaces: "Interfaces",
  io: "Inputs and outputs", callers: "Callers", dependencies: "Dependencies", external: "External", errors: "Errors",
  tests: "Tests", debug: "Debugging" };
function factHTML(row, body, cls) {
  const c = cls ? ` class="${cls}"` : "";
  const label = row.label || FACTS[row.key] || row.key;
  /* a key that names a file or symbol (components: model.py, src/app/) shows as code */
  const shown = !row.label && !FACTS[row.key] && /[./_]/.test(row.key) && !/\s/.test(row.key) ? `<code>${esc(label)}</code>` : esc(label);
  return `<dt${c}>${shown}</dt><dd${c}>${body}</dd>`;
}

/* ---------------------------------------------------------------- claims: evidence mark, chips, checker mark */
function evTip(c, extra) {
  const [name, note] = EV[c.evidence] || [c.evidence, ""];
  return `<b>${esc(name)}</b>${note ? " · " + esc(note) : ""}${extra ? " · " + extra : ""}`;
}
const anchorText = a => `${a.path}:${a.start === a.end ? a.start : a.start + "–" + a.end}`;
function chipsHTML(c, gone) {
  if (c.evidence === "searched_not_found") return `<button class="chip" data-claim="${esc(c.id)}" data-search="1">searched</button>`;
  return (c.anchors || []).map((a, i) => {
    const label = anchorText(a);
    return gone
      ? `<span class="chip gone" data-tip="The cited code is gone at <code>${esc(short(c.refreshed_to))}</code>">${esc(label)}</span>`
      : `<button class="chip" data-claim="${esc(c.id)}" data-i="${i}" aria-label="Show ${esc(label)}">${esc(label)}</button>`;
  }).join("");
}
function citeHTML(c, ctx) {
  if (!c) return `<span class="cite"><span class="rtag" data-tip="This claim isn't in the store any more">missing</span></span>`;
  const st = claimState(c), map = ctx === "map";
  if (c.evidence === "general_knowledge")
    return `<span class="cite"><span class="dot ev-general_knowledge" data-tip="${esc(evTip(c))}"></span><span class="gktag" data-tip="<b>General knowledge</b> · not from this repo; the Checker skips it">general knowledge</span></span>`;
  if (st === "retired") {
    const why = c.freshness_reason ? esc(c.freshness_reason) : "the cited code is gone";
    return `<span class="cite">${chipsHTML(c, true)}<span class="rtag" data-tip="<b>Retired</b> at <code>${esc(short(c.refreshed_to))}</code> · ${why}. Kept so you can see what changed; never served as fact.">retired</span></span>`
      + (map ? `<span class="rwhy-at" data-why="${why}"></span>` : "");
  }
  if (st === "stale_flagged")
    return `<span class="cite"><span class="stag" data-tip="<b>Stale.</b> The cited lines changed and the Checker re-read them: ${esc(c.check_note || "the claim no longer holds")}. Not served as fact.">stale</span>${chipsHTML(c)}<span class="flag" data-tip="<b>Not supported at the new lines.</b> ${esc(c.check_note || "")}">not supported</span></span>`;
  if (st === "stale") {
    const why = c.freshness_reason ? esc(c.freshness_reason) : "the cited lines changed";
    return `<span class="cite"><span class="stag" data-tip="<b>Stale, re-checking.</b> ${why} (at <code>${esc(short(c.refreshed_to))}</code>). Not served as fact, and not given to agents, until the Checker re-reads the new lines."><span class="spin"></span>stale, re-checking</span>${chipsHTML(c)}</span>`;
  }
  const checked = c.check && c.check !== "unchecked";
  if (map && unsupported(c)) return `<span class="cite"><span class="dot unsup" data-tip="${esc(nsTip(c))}" aria-hidden="true"></span>${chipsHTML(c)}</span>`;
  const dot = checked ? `<span class="dot ev-${esc(c.evidence)}" data-tip="${esc(evTip(c, c.check === "supported" ? "checked" : ""))}"></span>` : "";
  let mark = "";
  if (st === "rechecked") mark = `<span class="rck" data-tip="<b>Re-checked</b> · the cited lines changed in the last refresh; the Checker re-read them at <code>${esc(short((c.anchors || [])[0]?.commit))}</code>: still supported">↻</span>`;
  if (c.check === "not_supported") mark += `<span class="flag" data-tip="<b>Not supported.</b> ${esc(c.check_note || "The Checker re-read the cited lines and they don't say this.")}">not supported</span>`;
  else if (c.check === "supported" && !map && st !== "rechecked") mark += `<span class="ok" data-tip="<b>Checked</b> · the Checker re-read the cited lines: supported">✓</span>`;
  return `<span class="cite">${dot}${chipsHTML(c)}${mark}</span>`;
}

/* ---------------------------------------------------------------- the map */
let MAPTEXT = null;  // {text, blocks}
function renderMap() {
  const doc = D.map?.document;
  if (!doc) { renderNoMap(); return; }
  const byId = claimsById();
  MAPTEXT = mapText(doc);
  UI.mapRev = doc.revision;
  const flows = new Map((doc.flows || []).map(f => [f.id, f]));
  /* flows stay open, in the view the reader chose, when the map is re-rendered */
  const keepOpen = new Map($$(".flow.open", COL).map(f => [f.dataset.flow, f.classList.contains("view-list") ? "list" : "dg"]));
  buildFigures(doc, byId);
  let html = `<header><h1>${esc(doc.title || "Map")}</h1><p class="sub" id="sub"></p><div class="mem" id="mem"></div><div id="refresh"></div><div id="mapnew"></div><p class="hint">Select any text to ask about it or annotate it.</p></header>`;
  let bi = 0, graphShown = false;
  const mods = new Map((doc.sections || []).flatMap(x => x.blocks || []).filter(x => x.type === "module").map(x => [x.id, x]));
  /* the coverage note closes the Modules section (the Overview when there is none) */
  const covAt = (doc.sections || []).some(x => x.kind === "modules") ? "modules" : "overview";
  let covShown = false;
  for (const sec of doc.sections || []) {
    html += `<section id="s-${esc(sec.id)}" data-sec="${esc(sec.id)}"><h2>${esc(sec.title)}</h2>`;
    const blocks = sec.blocks || [];
    const topical = sec.kind === "overview" && blocks.some(x => x.topic);
    /* the module graph: after the Components group in a topic Overview, else after the first paragraph */
    const graphAfter = topical ? blocks.map(x => x.topic).lastIndexOf("components") : 0;
    let topic = null;
    blocks.forEach((block, k) => {
      const b = MAPTEXT.blocks[bi++];
      if (topical && block.topic && block.topic !== topic) {
        topic = block.topic;
        html += `<h3 class="topic" data-topic="${esc(topic)}">${esc(TOPICS[topic] || topic)}</h3>`;
      }
      let si = 0;
      const nextSeg = spans => segHTML(spans, b.segs[si++], byId);
      const own = block.spans && block.spans.length ? nextSeg(block.spans) : null;
      const claimed = segsOf(block).flat().filter(x => x.claim);
      const allGone = claimed.length > 0 && claimed.every(x => byId.get(x.claim)?.freshness === "retired");
      if (block.type === "module") {
        const design = block.design && block.design.length ? nextSeg(block.design) : null;
        const rows = (block.facts || []).map(r => [r, nextSeg(r.spans || [])]);
        const shown = rows.filter(([r]) => r.key === "responsibility"), more = rows.filter(([r]) => r.key !== "responsibility");
        const open = UI.openMods.has(block.id);
        const files = modFiles(block);
        const goneTip = ` data-tip="Every claim about ${files.length > 1 ? "these files" : "this file"} is retired"`;
        /* T7.13b: a component's heading is its title, its files as chips under it; an older block keeps path + role */
        const head = block.title
          ? `<div class="mod-h"><h3 class="mod-t${allGone ? " gone" : ""}"${allGone ? goneTip : ""}>${inlineCode(block.title)}</h3></div><div class="mod-files">${files.map(f => `<code>${esc(f)}</code>`).join("")}${block.entry ? `<span class="mtag">entry point</span>` : ""}</div>`
          : `<div class="mod-h"><code${allGone ? ` class="gone"${goneTip}` : ""}>${esc(block.path)}</code>${block.role ? `<span class="role">${esc(block.role)}</span>` : ""}</div>`;
        const rel = (block.related || []).map(id => mods.get(id)).filter(Boolean);
        const relHTML = rel.length ? `<span class="rel">Related: ${rel.map(m => `<a href="#" data-gomod="${esc(m.id)}" data-tip="${esc(m.title || modLabel(m))}">${esc(modName(m))}</a>`).join(`<span class="sep">·</span>`)}</span>` : "";
        const moreHTML = more.length ? `<button class="more" data-more="${esc(block.id)}" aria-expanded="${open}"><span class="mt">${open ? "Less" : "More"}</span><span class="mn">${plural(more.length, "fact")}</span></button>` : "";
        html += `<div class="mod${open ? " open" : ""}${block.title ? " comp" : ""}" data-block="${esc(block.id)}" data-path="${esc(files[0] || "")}">${head}`
          + (own !== null ? `<p class="blk">${own}</p>` : "")
          + (design !== null ? `<p class="blk design">${design}</p>` : "")
          + (rows.length ? `<dl class="facts mfacts">${shown.map(([r, h]) => factHTML(r, h)).join("")}${more.map(([r, h]) => factHTML(r, h, "fx")).join("")}</dl>` : "")
          + (moreHTML || relHTML ? `<div class="mod-foot">${moreHTML}${relHTML}</div>` : "")
          + `</div>`;
      } else if (block.type === "list") {
        const tag = block.ordered ? "ol" : "ul";
        html += `<div class="blist" data-block="${esc(block.id)}">${own !== null ? `<p class="blk lead">${own}</p>` : ""}<${tag}>`
          + (block.items || []).map(it => `<li>${nextSeg(it.spans || [])}</li>`).join("") + `</${tag}></div>`;
      } else if (block.type === "facts") {
        html += `<div class="bfacts" data-block="${esc(block.id)}">${own !== null ? `<p class="blk lead">${own}</p>` : ""}<dl class="facts">`
          + (block.rows || []).map(r => factHTML(r, nextSeg(r.spans || []))).join("") + `</dl></div>`;
      } else if (block.type === "flow") {
        const f = flows.get(block.flow);
        html += `<div class="flow" data-flow="${esc(block.flow)}" data-block="${esc(block.id)}"><button class="flow-h" aria-expanded="false"><span class="fq">${esc(f ? f.title : block.flow)}<span class="fcar">▸</span></span><span class="meta">${hgAv("tracer", "idle static", 20)}Tracer · ${plural(f ? f.hops.length : 0, "hop")}</span></button>`
          + `<p class="cap blk">${own ?? ""}</p><div class="fbody">`
          + (f ? `<div class="fbar"><span class="fhint">Hover or click an arrow for its code</span><span class="fviews" role="group" aria-label="View"><button data-fview="dg" class="on" aria-pressed="true">Diagram</button><button data-fview="list" aria-pressed="false">Steps</button></span></div>`
            + `<div class="fnarrow">Shown as steps while the panel is open: the diagram would be too small to read beside it. <button data-fview="dg">Show the diagram</button></div>`
            + `<figure class="fig wide" data-key="map:${esc(f.id)}"><div class="dgwrap"></div></figure><div class="rail">${pathHTML(f, byId, false)}</div>` : "") + `</div></div>`;
      } else html += `<p class="blk" data-block="${esc(block.id)}">${own ?? ""}</p>`;
      if (sec.kind === "overview" && !graphShown && k >= graphAfter && FIGS.has("graph")) {
        graphShown = true;
        html += `<figure class="fig wide" id="ovgraph" data-key="graph"><div class="dgwrap"></div></figure>${graphIsoHTML()}<p class="figcap wide" id="ovcap">${graphCaption()}</p>`;
      }
    });
    if (doc.coverage && !covShown && sec.kind === covAt) { covShown = true; html += coverageHTML(doc.coverage); }
    html += `</section>`;
  }
  COL.innerHTML = html;
  for (const [id, view] of keepOpen) if ($(`.flow[data-flow="${CSS.escape(id)}"]`, COL)) openFlow(id, view, false);
  document.body.classList.remove("nomap-on");
  renderToc();
  renderNeeds();
  index();
  renderHeader();
  applyOverlays();
  renderFigs();
}
/* T7.13b: a module block's files (a component may span several; an older block has its path), its short name for
   "Related" links (its role without a leading "the", capitalised: "the training loop" -> "Training loop"; else its
   title), and its label in the panel ("train.py + optim.py") */
function modFiles(b) { return b.files && b.files.length ? b.files : b.path ? [b.path] : []; }
function modName(b) {
  const r = (b.role || "").replace(/^the\s+/i, "");
  return r ? r[0].toUpperCase() + r.slice(1) : b.title || b.path || b.id;
}
function modLabel(b) { const f = modFiles(b); return f.length > 1 ? f.join(" + ") : f[0] || b.title || ""; }
/* the quiet note at the end of the Modules section: what the Cartographer read in full, skimmed and left out, each
   with its reason (meta.json's coverage; not plain text, so not part of what can be asked about) */
const COVERAGE = [["deep", "Read in full"], ["scanned", "Skimmed"], ["skipped", "Left out"]];
function coverageHTML(cov) {
  const rows = COVERAGE.filter(([k]) => (cov[k] || []).length).map(([k, label]) => `<dt>${label}</dt><dd>${cov[k].map(x => `<div class="cv"><span class="ca">${inlineCode(x.area || "")}</span><span class="csep">: </span><span class="cw">${inlineCode(x.why || "")}</span></div>`).join("")}</dd>`);
  return rows.length ? `<aside class="cov" aria-label="What this map covers"><h3 class="topic">What this map covers</h3><dl class="facts covl">${rows.join("")}</dl></aside>` : "";
}
function goModuleId(id) {
  const m = $(`.mod[data-block="${CSS.escape(id)}"]`, COL);
  if (!m) return;
  scrollMapTo(m, 80);
  flash(m);
}
function setModOpen(mod, open) {
  if (!mod) return;
  mod.classList.toggle("open", open);
  if (open) UI.openMods.add(mod.dataset.block); else UI.openMods.delete(mod.dataset.block);
  const b = $(".more", mod);
  if (b) { b.setAttribute("aria-expanded", String(open)); $(".mt", b).textContent = open ? "Less" : "More"; }
}
function renderNoMap() {
  MAPTEXT = null; UI.mapRev = null;
  const carto = D.activity.working.filter(w => w.agent === "cartographer" && !w.stale);
  COL.innerHTML = `<div class="nomap">${LOGO}<h1>No map yet</h1>
    <p>Honeyguide has no map of <b>${esc(REPO_NAME)}</b> yet.</p>
    <ol><li>Open Claude Code in this repository, with the Honeyguide plugin installed.</li>
    <li>Ask it to map the repo. The ${agHTML("cartographer")} reads the code and saves a map in which every claim cites its lines.</li>
    <li>This page shows the map as soon as it is saved; you don't need to reload.</li></ol>
    ${carto.map(workHTML).join("")}
    <p class="quiet">Memory for this repo lives outside the checkout, in <code>~/.honeyguide/</code> (or <code>$HONEYGUIDE_HOME</code>).</p></div>`;
  $("#toc").innerHTML = "";
  $("#needs").innerHTML = "";
  $("#repo").textContent = REPO_NAME;
  document.body.classList.add("nomap-on");
}
function renderToc() {
  const doc = D.map?.document;
  if (!doc) return;
  $("#toc").innerHTML = (doc.sections || []).map(s => `<li><a href="#s-${esc(s.id)}" data-sec="${esc(s.id)}" title="${esc(s.title)}"><span class="ini" aria-hidden="true">${esc((s.title || "?").trim()[0].toUpperCase())}</span><span class="tt">${esc(s.title)}</span><span class="n"></span></a></li>`).join("");
  spy();
}
/* T7.15: "Needs a look (N)" in the sidebar: every map claim the Checker marked not supported, in the order the map
   shows them, with the phrase the map shows and its section; click one to go to it and read the Checker's note. */
function needsList() {
  const doc = D.map?.document;
  if (!doc) return [];
  const flagged = new Map((D.map.claims || []).filter(unsupported).map(c => [c.id, c]));
  const out = new Map();
  for (const sec of doc.sections || []) for (const b of sec.blocks || []) for (const seg of segsOf(b)) for (const sp of seg)
    if (sp.claim && flagged.has(sp.claim) && !out.has(sp.claim)) out.set(sp.claim, { c: flagged.get(sp.claim), text: sp.text, sec: sec.title });
  const flowsTitle = secTitle(flowsSection()) || "Flows";
  for (const f of doc.flows || []) for (const h of f.hops || [])
    if (h.claim && flagged.has(h.claim) && !out.has(h.claim)) out.set(h.claim, { c: flagged.get(h.claim), text: h.call, sec: flowsTitle, flow: f.id, code: true });
  for (const [id, c] of flagged) if (!out.has(id)) out.set(id, { c, text: c.text, sec: "" });
  return [...out.values()];
}
function renderNeeds() {
  const el = $("#needs");
  const items = needsList();
  if (!items.length) { el.innerHTML = ""; return; }
  const open = !!UI.needsOpen;
  el.innerHTML = `<button class="nd-h" data-needs-tog aria-expanded="${open}" aria-controls="ndl" data-tip="Claims the Checker marked not supported: the cited lines don't show all of what the claim says. Each keeps a quiet mark on the map; hover it for the Checker's note."><span class="dot unsup" aria-hidden="true"></span><span class="tt">Needs a look</span><span class="n">${items.length}</span><span class="car" aria-hidden="true">${open ? "▾" : "▸"}</span></button>`
    + `<ol class="ndl" id="ndl"${open ? "" : " hidden"}>` + items.map(x => `<li><a href="#" data-ns="${esc(x.c.id)}"${x.flow ? ` data-nsflow="${esc(x.flow)}"` : ""} data-tip="${esc(nsTip(x.c))}"><span class="ns-t">${x.code ? `<code>${esc(clip(x.text, 48))}</code>` : inlineCode(clip(x.text.replace(/\s+/g, " ").trim(), 64))}</span>${x.sec ? `<span class="ns-s">${esc(x.sec)}</span>` : ""}</a></li>`).join("") + `</ol>`;
}
function goNeeds(id, flow) {
  let el = $(`.claim.quiet[data-claim="${CSS.escape(id)}"]`, COL);
  if (el) {
    const mod = el.closest(".mod");
    if (mod && el.closest(".fx") && !mod.classList.contains("open")) { setModOpen(mod, true); layout(); }
  } else if (flow) {
    const f = openFlow(flow, "list");
    el = f && $(`.hop[data-claim="${CSS.escape(id)}"]`, f);
  }
  if (!el) return;
  scrollMapTo(el);
  flash(el);
  if (el.matches(".claim")) el.focus({ preventScroll: true });
  setTimeout(() => showTip(el, el.dataset.tip || $(".node", el)?.dataset.tip), 60);
}
function blockAt(off) { return MAPTEXT?.blocks.find(b => off >= b.start && off < b.end) || MAPTEXT?.blocks.find(b => off <= b.end) || null; }

/* ---------------------------------------------------------------- Tracer path (map flows and panel answers) */
/* One rule for the rail and the diagram (Han's v3.1 choice 1): solid = read in source or seen at runtime (the
   evidence shape says which), dashed = inferred (neither read nor seen), dotted = a trace blind spot. */
const READ_OR_SEEN = new Set(["read_in_source", "asserted_by_test", "seen_at_runtime"]);
const hopStyle = (h, c) => (h.trace === "blind_spot" ? "dotted" : h.trace === "seen" || READ_OR_SEEN.has(c?.evidence) ? "solid" : "dashed");
/* the evidence shape a hop shows: none while its claim is stale, retired or missing, or (in the panel) unchecked */
function shownEv(c, panel) {
  if (!c) return null;
  const st = claimState(c);
  if (st === "retired" || st.startsWith("stale")) return null;
  if (c.check === "not_supported") return null;   /* T7.15: the dashed mark replaces the evidence shape */
  if (panel && (!c.check || c.check === "unchecked")) return null;
  return c.evidence;
}
/* what a hop hands on: [name, shape], the same words on the rail and on the diagram's pill */
const hopEdge = h => (h.returns && h.data ? [h.returns, h.data] : h.returns ? ["returns", h.returns] : h.data ? ["data", h.data] : null);
const hopAnchor = c => (!c ? "" : c.evidence === "searched_not_found" ? "searched" : (c.anchors || [])[0] ? anchorText(c.anchors[0]) : c.evidence === "general_knowledge" ? "general knowledge" : "");
function hopNote(h, style) {
  if (h.trace === "blind_spot") return ["Trace blind spot:", h.note || "the runtime trace can't see inside this call"];
  if (style === "dashed") return ["Inferred.", h.note || h.label || "neither read in source nor seen at runtime"];
  return h.note ? ["", h.note] : null;
}
function pathHTML(p, byId, panel) {
  const lanes = new Map((p.lanes || []).map(l => [l.id, l]));
  const loops = new Map((p.loops || []).map(l => [l.id, l]));
  const counts = {};
  const hops = (p.hops || []).map((h, i) => {
    const c = byId.get(h.claim);
    const ev = c ? c.evidence : "inferred";
    const st = claimState(c);
    const shown = shownEv(c, panel), style = hopStyle(h, c), note = hopNote(h, style);
    counts[ev] = (counts[ev] || 0) + 1;
    const tag = i === 0 ? "entry" : i === p.hops.length - 1 ? "end" : "";
    const to = lanes.get(h.to);
    const loop = h.loop && loops.get(h.loop);
    const tr = h.trace === "unseen" ? `<span class="tr">not in the runtime trace</span>` : h.trace === "blind_spot" ? `<span class="tr">trace blind spot</span>` : "";
    const quiet = !panel && unsupported(c);
    const ok = panel && c?.check === "supported" && st !== "stale" ? `<span class="ok" data-tip="<b>Checked</b> · the Checker re-read the cited lines: supported">✓</span>`
      : quiet ? `<span class="sr">Not supported: ${esc(c.check_note || NS_DEFAULT)}</span>`
      : c?.check === "not_supported" ? `<span class="flag" data-tip="<b>Not supported.</b> ${esc(c.check_note || "")}">not supported</span>` : "";
    const e = hopEdge(h);
    const edge = e ? `<li class="edge"><span><b>${esc(e[0])}</b>${esc(e[1])}</span></li>` : "";
    return `<li class="hop s-${style}${quiet ? " quiet" : ""}" data-hop="${i}" data-claim="${esc(h.claim || "")}"><span class="node ${shown ? "ev-" + esc(shown) : unsupported(c) ? "unsup" : "pending"}" data-tip="${c ? esc(unsupported(c) ? nsTip(c) : evTip(c)) : ""}"></span><div class="hop-b">`
      + `<div class="hop-t"><span class="fn">${esc(h.call)}</span>${tag ? `<span class="loop">${tag}</span>` : ""}${loop ? `<span class="loop" data-tip="Repeats: ${esc(loop.label)}">${esc(loop.label)}</span>` : ""}</div>`
      + (h.label ? `<div class="hop-d">${inlineCode(h.label)}</div>` : "")
      + (note && h.trace === "blind_spot" ? `<div class="hop-blind"><b>${esc(note[0])}</b> ${esc(note[1])}</div>` : note && h.note ? `<div class="hop-blind">${note[0] ? `<b>${esc(note[0])}</b> ` : ""}${esc(note[1])}</div>` : "")
      + `<div class="hop-l">${to ? `<span class="lane">${esc(to.label)}</span>` : ""}<span class="lab ev-${esc(ev)}">${esc((EV[ev] || [ev])[0].toLowerCase())}</span>${tr}${c ? chipsHTML(c, st === "retired") : ""}${ok}</div>`
      + `</div></li>${edge}`;
  }).join("");
  const foot = `<div class="path-foot">${Object.entries(counts).map(([ev, n]) => `<span><span class="dot ev-${esc(ev)}"></span>${n} ${esc((EV[ev] || [ev])[0].toLowerCase())}</span>`).join("")}</div>`;
  return `<ol class="path">${hops}</ol>${foot}`;
}

/* ---------------------------------------------------------------- flow diagrams and the module graph (T7.4) */
/* Models for diagrams.js, built from the contract's records: map flows ("map:<flow id>"), Tracer answers
   ("resp:<response id>") and the module graph ("graph"). Re-rendered only when the width they get changes. */
const FIGS = new Map();
const EVNAMES = Object.fromEntries(Object.entries(EV).map(([k, [n]]) => [k, n.toLowerCase()]));
/* T7.15: the Modules components, for the module graph (one box each) and the lanes' subtitles: a path maps to the
   component listing it, or to the one whose directory holds it (diagrams.js resolver) */
function components(doc) {
  const out = [];
  for (const sec of doc?.sections || []) for (const b of sec.blocks || []) {
    if (b.type !== "module") continue;
    const role = b.role || (b.title && b.title.includes(": ") ? b.title.slice(b.title.indexOf(": ") + 2) : "");
    const files = modFiles(b);
    out.push({ id: b.id, name: HGD.compName({ id: b.id, files }), role, files, entry: !!b.entry, module: b.id, title: b.title || "", label: modName(b) });
  }
  return out;
}
function diagramModel(p, byId, panel, key) {
  const compOf = HGD.resolver(components(D.map?.document));
  const lanes = {};
  for (const l of p.lanes || []) lanes[l.id] = { name: l.label, sub: (l.path && compOf(l.path)?.role) || "", file: l.path || null };
  const loops = {};
  for (const l of p.loops || []) loops[l.id] = l.label;
  const hops = (p.hops || []).map(h => {
    const c = byId.get(h.claim), style = hopStyle(h, c);
    return { fn: h.call, a: hopAnchor(c), ev: shownEv(c, panel), style, note: hopNote(h, style), d: h.label || "", trace: h.trace,
      from: h.from, to: h.to, edge: hopEdge(h), loop: h.loop || null, claim: h.claim,
      chip: c && (c.anchors || []).length ? 0 : null, search: c?.evidence === "searched_not_found",
      ns: unsupported(c) ? c.check_note || NS_DEFAULT : null };
  });
  /* the graph's start label: the starting lane's label without its file (e.g. "train.py · main" -> "main") */
  const l0 = (p.lanes || []).find(l => l.id === p.hops?.[0]?.from);
  const fileName = l0?.path ? [l0.path, l0.path.split("/").pop()].find(x => l0.label.startsWith(x)) : null;
  const startLabel = l0 ? (fileName ? l0.label.slice(fileName.length).replace(/^[\s·:]+/, "") || l0.label : l0.label) : "";
  return { key, id: p.id, title: p.title, lanes, loops, hops, evNames: EVNAMES, startLabel };
}
function buildFigures(doc, byId) {
  for (const k of [...FIGS.keys()]) if (!k.startsWith("resp:")) FIGS.delete(k);
  const flows = (doc.flows || []).map(f => diagramModel(f, byId, false, `map:${f.id}`));
  flows.forEach(m => FIGS.set(m.key, m));
  const gm = HGD.graphModel(flows, components(doc));
  if (gm.edges.length || gm.starts.length) FIGS.set("graph", gm);
}
function graphCaption() {
  const gm = FIGS.get("graph"), n = gm.edges.reduce((s, e) => s + e.calls.length, 0);
  return `Each box is a component from Modules, named by its first file. The ${plural(n, "call")} that cross from one component to another in the ${plural(gm.flows, "traced flow")} (<a href="#s-${esc(flowsSection())}" data-goflows>Flows</a>, below) are drawn as arrows, heavier when there are more. Hover a box for its files; click it for its module, an arrow for its calls.`;
}
/* the components no traced flow passes through: one quiet line under the graph, each a link to its module */
function graphIsoHTML() {
  const gm = FIGS.get("graph");
  const iso = gm.iso.map(id => gm.comps.find(c => c.id === id)).filter(Boolean);
  if (!iso.length) return "";
  return `<p class="figiso wide" id="ovgraph-iso"><span class="fi-l">Not in a traced flow:</span> ${iso.map(c => c.module
    ? `<a href="#" data-gomod="${esc(c.module)}" data-tip="${esc(`${c.title ? inlineCode(c.title) : esc(c.name)}<br>Files: ${c.files.map(f => `<code>${esc(f)}</code>`).join(", ")}`)}">${esc(c.label || c.name)}</a>`
    : `<code>${esc(c.name)}</code>`).join(`<span class="sep"> · </span>`)}</p>`;
}
function flowsSection() { return (D.map?.document?.sections || []).find(s => s.kind === "flows")?.id || "flows"; }
/* the width a figure gets: the map area (less the panel when it is open), 560 to 1000 px */
function panelWidth() { return parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--pw")) || 408; }
function figWidth() { return Math.round(Math.max(560, Math.min(1000, MAIN.clientWidth - (UI.open ? panelWidth() : 0) - 48))); }
function figSVG(key, w) {
  const m = FIGS.get(key);
  if (!m) return "";
  return key === "graph" ? HGD.renderGraph(HGD.layoutGraph(m, w)) : HGD.renderSeq(HGD.layoutSeq(m, w), m);
}
/* Han's v3.1 choice 7: with the panel open, a flow whose diagram would scale below 0.85 shows its steps instead
   (readable text over a shrunken picture); "Show the diagram" or View as diagram overrides that for the flow. */
const MIN_SCALE = 0.85;
function tooNarrow(key, w) { const m = FIGS.get(key); return !!m && UI.open && w / HGD.layoutSeq(m, w).natural < MIN_SCALE; }
function renderFigs(force) {
  const w = figWidth();
  document.documentElement.style.setProperty("--fw", w + "px");
  for (const fl of $$(".flow", COL)) {
    const key = `map:${fl.dataset.flow}`;
    const auto = fl.classList.contains("open") && !fl.classList.contains("view-list") && !fl.dataset.force && tooNarrow(key, w);
    fl.classList.toggle("view-auto", auto);
    $$("[data-fview]", $(".fviews", fl) || fl).forEach(b => { const on = auto ? b.dataset.fview === "list" : (b.dataset.fview === "list") === fl.classList.contains("view-list"); b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  }
  for (const fig of [...$$(".fig[data-key]", COL), $("#dgovfig")]) {
    if (!fig || !fig.dataset.key || (!force && fig.offsetParent === null)) continue;
    if (!force && +fig.dataset.w === w) continue;
    if (pinned && fig.contains(pinned)) unpin();
    fig.dataset.w = w;
    $(".dgwrap", fig).innerHTML = figSVG(fig.dataset.key, w - 2);
    /* a sequence diagram shown anyway in too little room (the overlay, or "Show the diagram") keeps 0.85 and
       scrolls sideways rather than shrinking its text further */
    const svg = $("svg.dg-seq", fig);
    const floored = !!svg && (w - 2) / +svg.dataset.natural < MIN_SCALE;
    if (floored) svg.style.width = Math.round(+svg.dataset.natural * MIN_SCALE) + "px";
    fig.classList.toggle("scrolls", floored);
  }
}
function openFlow(id, view = "dg", draw = true) {
  const f = $(`.flow[data-flow="${CSS.escape(id)}"]`, COL);
  if (!f) return null;
  f.classList.add("open");
  $(".flow-h", f).setAttribute("aria-expanded", "true");
  f.classList.toggle("view-list", view === "list");
  if (view === "list") delete f.dataset.force;
  if (draw) { renderFigs(); layout(); }
  return f;
}
function flashFig(el) { el.classList.remove("flashfig"); void el.getBoundingClientRect(); el.classList.add("flashfig"); setTimeout(() => el.classList.remove("flashfig"), 1800); }
/* "View as diagram" from a rail in the panel: a map flow scrolls to its diagram and flashes it; a Tracer answer that
   is not a map flow opens in an overlay over the map (never over the panel). Jumps are instant (choice 9). */
function mapFlowOf(key) {
  if (key.startsWith("map:")) return key.slice(4);
  const r = IDX.R.get(key.slice(5)), p = r?.path;
  const f = p && (D.map?.document?.flows || []).find(x => x.id === p.id && x.title === p.title);
  return f ? f.id : null;
}
function viewDiagram(key) {
  const id = mapFlowOf(key);
  if (id) {
    const f = $(`.flow[data-flow="${CSS.escape(id)}"]`, COL);
    if (!f) return null;
    f.dataset.force = "1";
    openFlow(id, "dg");
    const fig = $(".fig", f);
    MAIN.scrollTop += f.getBoundingClientRect().top - MAIN.getBoundingClientRect().top - 24;
    flashFig(fig);
    return fig;
  }
  const m = FIGS.get(key);
  if (!m) return null;
  const ov = $("#dgov"), fig = $("#dgovfig");
  fig.dataset.key = key;
  fig.dataset.w = "";
  $("#dgovt").textContent = m.title;
  $("#dgovs").textContent = "Tracer answer, as a diagram · not part of the map";
  ov.classList.add("on");
  ov.dataset.from = key;
  renderFigs();
  ov.scrollTop = 0;
  $("[data-dgclose]", ov).focus({ preventScroll: true });
  return fig;
}
function closeOverlay() {
  const ov = $("#dgov");
  if (!ov.classList.contains("on")) return;
  if (pinned && ov.contains(pinned)) unpin();
  ov.classList.remove("on");
  $("#dgovfig").dataset.key = "";
  $(".dgwrap", $("#dgovfig")).innerHTML = "";
  $(`[data-dgview="${CSS.escape(ov.dataset.from || "")}"]`, PBODY)?.focus({ preventScroll: true });
}
/* the module graph: an arrow leads to the calls it counts, a box to its module (both by component id) */
function showCalls(from, to) {
  const hits = [], gm = FIGS.get("graph"), e = gm?.edges.find(x => x.from === from && x.to === to);
  for (const c of e?.calls || []) if (c.flow.startsWith("map:")) hits.push({ id: c.flow.slice(4), i: c.hop });
  if (!hits.length) return;
  for (const x of hits) { const f = openFlow(x.id, "dg", false); if (f) f.dataset.force = "1"; }
  renderFigs();
  layout();
  const f = $(`.flow[data-flow="${CSS.escape(hits[0].id)}"]`, COL);
  MAIN.scrollTop += f.getBoundingClientRect().top - MAIN.getBoundingClientRect().top - 24;
  for (const x of hits) {
    const g = $(`.fig[data-key="map:${CSS.escape(x.id)}"] .dg-a[data-kind="call"][data-hop="${x.i}"]`, COL);
    if (g) { g.classList.add("hl"); setTimeout(() => g.classList.remove("hl"), 2400); }
  }
}
function goModule(comp) {
  const c = FIGS.get("graph")?.comps.find(x => x.id === comp);
  if (c?.module) goModuleId(c.module);
}
/* the line a diagram's preview gains: "Hop 6 of 7 · loss.backward() · seen at runtime", its description, its note */
function hopCtxHTML(g) {
  const m = FIGS.get(g.dataset.key), i = +g.dataset.hop, h = m?.hops[i], k = g.dataset.kind;
  if (!h) return "";
  const what = k === "call" ? `<code>${esc(h.fn)}</code>` : `${k === "ret" ? "returns" : "hands on"} <code>${esc(h.edge.filter(Boolean).join(" "))}</code>`;
  const ev = h.ev ? EVNAMES[h.ev] : h.ns ? "not supported" : "not checked yet";
  const tr = h.trace === "seen" ? "seen at runtime" : h.trace === "blind_spot" ? "trace blind spot" : "not in the runtime trace";
  const evw = h.ev === "seen_at_runtime" && h.trace === "seen" ? ev : `${ev} · ${tr}`;
  return `<div class="snip-ctx"><div class="sc-h">${h.ev ? `<span class="dot ev-${esc(h.ev)}"></span>` : ""}<b>Hop ${i + 1} of ${m.hops.length}</b><span>·</span>${what}<span>·</span><span>${esc(evw)}</span></div>`
    + `${h.d || h.note ? `<div class="sc-d">${h.d ? inlineCode(h.d) : ""}${h.note && h.note[0] !== "Inferred." ? `${h.d ? "<br>" : ""}${h.note[0] ? `<b>${esc(h.note[0])}</b> ` : ""}${esc(h.note[1])}` : ""}</div>` : ""}`
    + `${h.ns ? `<div class="sc-d sc-ns"><b>Not supported.</b> ${esc(h.ns)}</div>` : ""}</div>`;
}

/* ---------------------------------------------------------------- threads: index the store */
function index() {
  const Q = new Map(D.threads.questions.map(q => [q.id, q]));
  const R = new Map(D.threads.responses.map(r => [r.id, r]));
  const respOf = new Map();
  for (const r of D.threads.responses) respOf.set(r.parent, r);
  const kids = new Map();
  const roots = [];
  for (const q of D.threads.questions) {
    if (q.parent_response && R.has(q.parent_response)) {
      const pq = R.get(q.parent_response).parent;
      if (!kids.has(pq)) kids.set(pq, []);
      kids.get(pq).push(q.id);
    } else roots.push(q);
  }
  const groups = new Map();
  for (const q of roots) {
    const a = q.anchor;
    let key, range = null;
    if (a && a.doc === "map") {
      range = resolveMapAnchor(a);
      key = range ? `m:${range[0]}:${range[1]}` : `u:${a.quote}`;
    } else key = "general";
    if (!groups.has(key)) {
      const b = range ? blockAt(range[0]) : null;
      groups.set(key, { key, anchor: a && a.doc === "map" ? a : null, range, sec: b?.sec || null, mod: b?.block.type === "module" ? modLabel(b.block) : null, roots: [] });
    }
    groups.get(key).roots.push(q.id);
  }
  const groupOf = new Map();
  const walk = (g, id) => { groupOf.set(id, g.key); for (const k of kids.get(id) || []) walk(g, k); };
  for (const g of groups.values()) for (const id of g.roots) walk(g, id);
  IDX = { Q, R, respOf, kids, groups, groupOf };
}
function resolveMapAnchor(a) {
  if (!MAPTEXT) return null;
  if (a.revision === UI.mapRev) return [a.start, a.end];
  /* the map was regenerated: re-find the quote; several hits or none = unresolved (flagged, never guessed) */
  const t = MAPTEXT.text, i = t.indexOf(a.quote);
  if (i < 0 || t.indexOf(a.quote, i + 1) >= 0) return null;
  const s = cpLen(t.slice(0, i));
  return [s, s + cpLen(a.quote)];
}
function nodesIn(g) { const out = []; const walk = id => { out.push(id); for (const k of IDX.kids.get(id) || []) walk(k); }; g.roots.forEach(walk); return out; }
function pathTo(id) { const p = []; let q = IDX.Q.get(id); while (q) { p.unshift(q.id); q = q.parent_response ? IDX.Q.get(IDX.R.get(q.parent_response)?.parent) : null; } return p; }
function workingFor(qid) { return D.activity.working.filter(w => w.question === qid && !w.stale); }
function groupBusy(g) { return nodesIn(g).flatMap(workingFor); }
function secTitle(id) { return (D.map?.document?.sections || []).find(s => s.id === id)?.title || ""; }
function groupLabel(g) { return g.key === "general" ? "Whole repo" : g.mod || (g.sec ? g.sec.title : "The map"); }

/* ---------------------------------------------------------------- overlays on the map and on answers */
function wrapIn(leaf, a, b, make) {
  const out = [], nodes = [];
  const w = document.createTreeWalker(leaf, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) nodes.push(w.currentNode);
  let pos = 0;
  for (const t of nodes) {
    const s = t.data, n = cpLen(s), lo = Math.max(a, pos), hi = Math.min(b, pos + n);
    if (lo < hi) {
      let node = t;
      const i0 = cpIdx(s, lo - pos), i1 = cpIdx(s, hi - pos);
      if (i1 < s.length) node.splitText(i1);
      if (i0 > 0) node = node.splitText(i0);
      const el = make();
      node.parentNode.insertBefore(el, node);
      el.appendChild(node);
      out.push(el);
    }
    pos += n;
  }
  return out;
}
function highlight(root, s, e, make) {
  const out = [];
  for (const leaf of $$(".lf", root)) {
    const o = +leaf.dataset.o, len = cpLen(leaf.textContent);
    if (o < e && s < o + len) out.push(...wrapIn(leaf, Math.max(s, o) - o, Math.min(e, o + len) - o, make));
  }
  return out;
}
function clearOverlays(root) {
  for (const el of $$(".mk,.nt,.fmk", root)) { const p = el.parentNode; while (el.firstChild) p.insertBefore(el.firstChild, el); el.remove(); }
  for (const leaf of $$(".lf", root)) leaf.normalize();
  for (const m of $$(".mm", root)) m.remove();
}
const mk = (cls, data) => () => { const el = document.createElement("span"); el.className = cls; for (const [k, v] of Object.entries(data)) el.dataset[k] = v; return el; };

let MARKS = { groups: new Map(), notes: new Map() };
function applyOverlays() {
  if (!MAPTEXT || !IDX) return;
  clearOverlays(COL);
  MARKS = { groups: new Map(), notes: new Map() };
  for (const g of IDX.groups.values()) {
    if (!g.range) continue;
    const els = highlight(COL, g.range[0], g.range[1], mk("mk", { g: g.key }));
    const pill = document.createElement("button");
    pill.className = "mm"; pill.dataset.g = g.key;
    COL.appendChild(pill);
    MARKS.groups.set(g.key, { els, pill });
  }
  for (const n of D.notes.notes) {
    if (!n.anchor || n.anchor.doc !== "map") continue;
    const r = resolveMapAnchor(n.anchor);
    if (!r) continue;
    const els = highlight(COL, r[0], r[1], mk("nt", { n: n.id }));
    const pill = document.createElement("button");
    pill.className = "mm note"; pill.dataset.n = n.id; pill.setAttribute("aria-label", "Your note");
    pill.dataset.tip = `<b>Your note</b> · ${esc(clip(n.text, 80))}`;
    COL.appendChild(pill);
    MARKS.notes.set(n.id, { els, pill });
  }
  if (UI.compose && UI.compose.doc === "map") highlight(COL, UI.compose.start, UI.compose.end, mk("mk pend", {}));
  /* a discussion or note on a folded fact opens its module, so its mark is never hidden */
  for (const el of $$(".mk,.nt", COL)) if (el.closest("dd.fx")) setModOpen(el.closest(".mod"), true);
  renderMarks();
}
function renderMarks() {
  if (!MAPTEXT || !IDX) return;
  for (const [key, m] of MARKS.groups) {
    const g = IDX.groups.get(key);
    const n = nodesIn(g).length, busy = groupBusy(g).length > 0;
    const active = UI.open && UI.tab === "thread" && UI.cur === key;
    m.pill.textContent = n;
    m.pill.classList.toggle("busy", busy);
    m.pill.classList.toggle("active", active);
    m.pill.setAttribute("aria-label", `${plural(n, "question")} on this passage`);
    m.pill.dataset.tip = `<b>${plural(n, "question")}</b>${busy ? " · an agent is at work" : ""} · open the discussion`;
    m.els.forEach(el => el.classList.toggle("active", active));
  }
  for (const a of $$("#toc a")) {
    const c = [...IDX.groups.values()].filter(g => g.sec && g.sec.id === a.dataset.sec).length;
    $(".n", a).textContent = c || "";
  }
  layout();
}
function layout() {
  const col = COL.getBoundingClientRect();
  const items = [];
  const place = (els, pill) => { const r = els[0]?.getClientRects()[0]; if (r) items.push([pill, r.top - col.top + r.height / 2 - 9]); else pill.style.display = "none"; };
  for (const m of MARKS.groups.values()) place(m.els, m.pill);
  for (const m of MARKS.notes.values()) place(m.els, m.pill);
  items.sort((a, b) => a[1] - b[1]);
  let last = -99, shift = 0;
  for (const [el, top] of items) { shift = Math.abs(top - last) < 20 ? shift + 24 : 0; el.style.top = top + "px"; el.style.marginLeft = shift + "px"; last = top; }
}
function answerOverlays() {
  /* follow-up marks and notes inside rendered answers */
  for (const host of $$(".ans[data-doc]", PBODY)) {
    const rid = host.dataset.doc.slice(7);
    const r = IDX.R.get(rid);
    const len = cpLen(r?.text || "");
    for (const kid of IDX.kids.get(r?.parent) || []) {
      const a = IDX.Q.get(kid).anchor;
      if (!a || a.doc !== host.dataset.doc || (a.start === 0 && a.end >= len)) continue;
      highlight(host, a.start, a.end, mk("fmk", { go: kid }));
    }
    for (const n of D.notes.notes) if (n.anchor && n.anchor.doc === host.dataset.doc) highlight(host, n.anchor.start, n.anchor.end, mk("nt", { n: n.id }));
    if (UI.compose && UI.compose.doc === host.dataset.doc) highlight(host, UI.compose.start, UI.compose.end, mk("fmk pend", {}));
  }
}

/* ---------------------------------------------------------------- memory header */
function allClaims() { return [...claimsById().values()]; }
function renderHeader() {
  const s = D.state;
  if (!s || !MAPTEXT) return;
  const doc = D.map.document;
  const mapClaims = D.map.claims || [];
  const files = new Set(mapClaims.flatMap(c => (c.anchors || []).map(a => a.path)));
  $("#sub").textContent = `Mapped by the Cartographer · ${plural((doc.sections || []).length, "section")} · cites ${plural(files.size, "file")}`;
  /* the header is memory.memory_state, as /api/state returns it ("memory"): never "Up to date" while refreshing or behind */
  const m = s.memory || {};
  const fr = m.freshness || {};
  const stale = m.awaiting_recheck || 0;
  const headline = esc(m.headline || "").replace(/\b[0-9a-f]{12}\b/g, x => `<code>${x}</code>`);
  let h;
  if (m.state === "behind") {
    h = `<span class="mem-i warn">${ICON.info}</span><span data-tip="The map was saved at <code>${esc(short(m.map_commit))}</code>; HEAD is now <code>${esc(short(m.head))}</code>. A refresh re-resolves every claim against the new code.">${headline}</span>`;
  } else if (m.state === "refreshing") {
    h = `<span class="mem-i busy"><span class="ring"></span></span><span data-tip="The code changed since these claims were checked. They are shown greyed, without their evidence mark, and not served as fact or given to agents until the Checker re-reads the new lines.">${headline}</span>`;
  } else {
    h = `<span class="mem-i">${ICON.ok}</span><span data-tip="The map is at <code>${esc(short(m.head))}</code>, which is HEAD, and no claim waits for a re-check.">${headline}</span>`;
  }
  const live = (fr.current || 0) + (fr.stale || 0);
  const parts = [fr.stale ? `${fr.stale} stale` : "", fr.retired ? `${fr.retired} retired` : ""].filter(Boolean);
  h += `<span class="sep">·</span><span data-tip="Claims on the map and in answers">${plural(live, "claim")}${parts.length ? ", " + parts.join(", ") : ", every anchor resolved"}</span>`;
  const since = m.rechecked_since_visit || 0;
  if (since) h += `<span class="sep">·</span><span class="since">${plural(since, "claim")} re-checked since your last visit</span>`;
  if (m.dirty && m.dirty.tracked) h += `<span class="sep">·</span><span data-tip="${m.dirty.tracked} uncommitted change(s) in the working tree. The map and previews read committed code only.">uncommitted changes not mapped</span>`;
  $("#mem").innerHTML = h;
  $("#repo").textContent = `${doc.title || ""} @ ${short(m.head || s.head)}`;
  /* the refresh since the last visit */
  const last = m.last_refresh;
  const show = last && (!m.previous_visit || last.at > m.previous_visit) && UI.dismissed !== last.at;
  $("#refresh").innerHTML = show ? refreshHTML(last, stale) : "";
  $("#mapnew").innerHTML = UI.pendingRev ? `<div class="mapnew" role="status"><span>The Cartographer saved a new version of the map.</span><button data-reload>Show it</button></div>` : "";
}
function refreshHTML(e, stale) {
  const c = { ...(e.counts || {}) };
  if (typeof e.uncovered === "number") c.uncovered = e.uncovered;
  const LABEL = {
    moved: ["→", "moved", "Same lines at new line numbers: the anchors were updated; nothing to re-check", null],
    stale: ["↻", "changed", "The cited lines changed; the Checker re-reads each claim before it is served again", "stale"],
    retired: ["<span class=\"g ret\">abc</span>", "retired", "The cited code is gone; the claim stays, struck through, with its reason", "retired"],
    uncovered: ["+", "new code to map", "Code no claim covered; the Cartographer maps only that", null],
    new: ["+", "new sections", "Code no claim covered; the Cartographer mapped only that", null],
  };
  const btns = Object.entries(c).filter(([key, n]) => n > 0 && !["unchanged", "unanchored"].includes(key)).map(([key, n]) => {
    const L = LABEL[key];
    if (!L) return `<span class="c">${n} ${esc(key)}</span>`;
    const go = L[3] && $(`.claim[data-st="${L[3]}"],.claim[data-st="rechecked"]`) ? ` data-rfgo="${L[3]}"` : "";
    return `<button${go} data-tip="${esc(L[2])}">${L[0].startsWith("<") ? L[0] : `<span class="g">${L[0]}</span>`}${n} ${L[1]}</button>`;
  }).join("");
  const checker = D.activity.working.filter(w => w.agent === "checker" && !w.question && !w.stale);
  const work = stale ? (checker.length ? `<div class="rf-w">${avHTML("checker", true, "", 22)}<span><b>Checker</b> ${inlineCode(checker[0].status)}; not shown as fact until it finishes</span></div>`
    : `<div class="rf-w"><span>${plural(stale, "stale claim")} waiting for the ${agHTML("checker")}; not shown as fact until re-checked</span></div>`) : "";
  return `<div class="refresh" role="status"><div class="rf-h"><span class="i">${ICON.rf}</span><b>Refreshed since your last visit</b><span>· updated from <code>${esc(short(e.base))}</code> to <code>${esc(short(e.target))}</code></span><button class="x" data-rfx="${esc(e.at)}" aria-label="Dismiss">×</button></div>`
    + (btns ? `<div class="rf-c">${btns}</div>` : "") + (e.note ? `<div class="rf-n">${inlineCode(e.note)}</div>` : "") + work + `</div>`;
}

/* ---------------------------------------------------------------- agents */
/* The .av wrapper keeps data-tip, the .working hook and the reduced-motion badge; hgAv draws the creature. state
   defaults to working or idle; "… static" never moves. extra: more attributes for the wrapper (the answer header's
   data-hop). */
const AV_STATE = { true: "working", false: "idle" };
const avHTML = (ag, working, tip, size = 28, state, extra = "") => {
  tip = tip === null ? "" : tip || (ag === "guide" ? HONEY : "");   /* null: no tip of its own (the top bar has one) */
  return `<span class="av a-${esc(ag)}${working ? " working" : ""}"${tip ? ` data-tip="${esc(tip)}"` : ""}${extra} aria-hidden="true">`
    + hgAv(AG[ag] ? ag : "guide", state || AV_STATE[!!working], size) + `</span>`;
};
/* The answer header shows its agent "done". The hop plays once per answer per page load: the HTML always says
   "done static" (so a poll's re-render is byte-identical and never rebuilds it), and the first time an answer's
   header is put in the DOM its avatar loses "static", hops once and holds the done pose. Any later rebuild renders
   it still. */
const byAvHTML = r => avHTML(r.agent, false, "", 28, "done static", ` data-hop="${esc(r.id)}"`);
function playHops(root) {
  for (const el of $$(".av[data-hop]", root)) {
    if (UI.hopped.has(el.dataset.hop)) continue;
    UI.hopped.add(el.dataset.hop);
    el.firstElementChild?.classList.remove("hg-av-static");
  }
}
function workHTML(w, ctx, size = 40) {
  return `<div class="work">${avHTML(w.agent, true, "", size)}<div><b>${esc(agName(w.agent))}</b>${inlineCode(w.status)}${ctx ? `<span class="wctx">· ${esc(ctx)}</span>` : ""}</div></div>`;
}
function renderTop() {
  const top = $("#top");
  if (!D.map?.document && !D.threads.questions.length) { top.style.display = "none"; return; }
  top.style.display = "";
  const w = D.activity.working.filter(x => !x.stale);
  const nT = IDX ? IDX.groups.size : 0;
  if (w.length) {
    const ags = [...new Set(w.map(x => x.agent))];
    top.classList.add("busy");
    top.innerHTML = `<span class="mini">${ags.map(a => avHTML(a, true, null, 24)).join("")}</span><span>${ags.length} at work</span>`;
    top.dataset.tip = w.map(x => `<b>${esc(agName(x.agent))}</b> ${inlineCode(x.status)}`).join("<br>");
  } else {
    top.classList.remove("busy");
    top.innerHTML = `${ICON.msg}<span>Discussions</span>${nT ? `<span class="cnt">${nT}</span>` : ""}`;
    delete top.dataset.tip;
  }
}

/* ---------------------------------------------------------------- the discussion panel */
function answerHTML(q, r, byId) {
  const doc = `answer:${r.id}`;
  const spans = r.spans || [{ text: r.text }];
  const body = spansHTML(spans, 0, "answer", byId);
  const shown = new Set(spans.map(s => s.claim).filter(Boolean));
  for (const h of r.path?.hops || []) shown.add(h.claim);
  const extra = (r.claims || []).filter(c => !shown.has(c.id));
  const extraHTML = extra.length ? `<ul class="ans-claims">${extra.map(c => `<li><span class="claim">${inlineCode(c.text)}</span>${citeHTML(c, "answer")}</li>`).join("")}</ul>` : "";
  if (r.path) FIGS.set(`resp:${r.id}`, diagramModel(r.path, byId, true, `resp:${r.id}`));
  const path = r.path ? `${pathHTML(r.path, byId, true)}<button class="dglink" data-dgview="resp:${esc(r.id)}">${ICON.dg}View as diagram</button>` : "";
  return `<div class="ans" data-doc="${esc(doc)}"><div class="atext">${body}</div>${extraHTML}${path}</div>`;
}
function checkHTML(q, r) {
  const busy = workingFor(q.id).filter(w => w.agent === "checker");
  if (busy.length) return busy.map(w => workHTML(w)).join("");
  const cs = r.claims || [];
  const gk = cs.filter(c => c.evidence === "general_knowledge").length;
  const tot = cs.length - gk;
  const sup = cs.filter(c => c.check === "supported").length, ns = cs.filter(c => c.check === "not_supported").length;
  const un = cs.filter(c => c.evidence !== "general_knowledge" && (!c.check || c.check === "unchecked")).length;
  if (!tot) return gk ? `<div class="chk">${plural(gk, "general-knowledge claim")}; nothing in the repo to check</div>` : "";
  if (un === tot) return `<div class="chk" data-tip="Answers show at once; each claim gains its evidence mark when the Checker has re-read its lines">Not checked yet · ${plural(tot, r.path ? "hop" : "claim")} waiting for the ${agHTML("checker")}</div>`;
  return `<div class="chk" data-tip="${plural(tot, r.path ? "hop" : "claim")} checked against their cited lines${gk ? `; ${plural(gk, "general-knowledge claim")} skipped` : ""}"><span class="em">✅</span>${sup} of ${tot} supported${un ? ` · ${un} not checked yet` : ""}${gk ? ` · ${gk} general, not checked` : ""}</div>`;
}
function nodeHTML(id, byId) {
  const q = IDX.Q.get(id), r = IDX.respOf.get(id);
  const kids = (IDX.kids.get(id) || []).map(k => nodeHTML(k, byId)).join("");
  const a = q.anchor;
  const parentText = q.parent_response ? IDX.R.get(q.parent_response)?.text || "" : "";
  const whole = a && q.parent_response && a.start === 0 && a.end >= cpLen(parentText);
  const on = q.parent_response && a && !whole ? `<span class="on-q"><b>on</b><q>${esc(clip(qt(a.quote), 60))}</q></span>` : "";
  let body = "";
  const work = workingFor(id).filter(w => w.agent !== "checker" || q.status !== "answered");
  if (q.status === "answered" && r) {
    const via = r.agent === "tracer" ? `· routed by ${agHTML("guide")} as a flow question` : "· answer";
    const saved = D.notes.notes.some(n => n.from_response === r.id);
    body = `<div class="by">${byAvHTML(r)}<span class="who">${esc(agName(r.agent))}</span><span class="via">${via}</span></div>`
      + answerHTML(q, r, byId) + checkHTML(q, r)
      + `<div class="acts"><button data-save="${esc(r.id)}" class="${saved ? "done" : ""}">${saved ? "Saved to notes ✓" : "Save as note"}</button><button data-copyans="${esc(r.id)}">Copy</button></div>`;
  } else if (q.status === "failed") {
    body = `<div class="failed">${avHTML(q.agent || "investigator", false, "", 20, "failed")}Couldn't answer: ${esc(q.error || "the agent stopped")}<button data-retry="${esc(id)}">Retry</button></div>`;
  } else if (work.length) {
    body = work.map(w => workHTML(w)).join("") + `<div class="shim w1"></div><div class="shim w2"></div>`;
  } else if (q.status === "investigating") {
    body = `<div class="work">${avHTML(q.agent || "investigator", true, "", 40)}<div><b>${esc(agName(q.agent || "investigator"))}</b>is working on it</div></div><div class="shim w1"></div><div class="shim w2"></div>`;
  } else {
    body = `<div class="wait">${avHTML("guide", false, "", 28, "waiting")} Waiting for the Guide. Your Claude Code session picks questions up while it runs <code>honeyguide watch</code>.</div>`;
  }
  const busy = q.status !== "answered" && q.status !== "failed";
  const meta = `${agHTML(r ? r.agent : "guide")} · ${busy ? "working" : r ? plural((r.claims || []).length, r.path ? "hop" : "claim") : "failed"}${kids ? ` · ${plural((IDX.kids.get(id) || []).length, "follow-up")}` : ""}`;
  const onp = UI.curNode && id !== UI.curNode && pathTo(UI.curNode).includes(id);
  const closed = UI.closed.has(id);
  return `<div class="nd${closed ? " closed" : ""}${onp ? " onpath" : ""}${id === UI.curNode ? " cur" : ""}" data-id="${esc(id)}">
    <div class="nd-q"><button class="car" data-tog="${esc(id)}" aria-label="${closed ? "Expand" : "Collapse"}" aria-expanded="${!closed}">▼</button><div><button class="qt" data-node="${esc(id)}">${on}${esc(q.text)}</button><span class="meta1">${meta}</span></div></div>
    <div class="nd-b">${body}</div>${kids ? `<div class="kids">${kids}</div>` : ""}</div>`;
}
function crumbsHTML(g) {
  let h = `<button data-crumb="" title="${esc(groupLabel(g))}">${esc(groupLabel(g))}</button>`;
  if (UI.curNode && IDX.Q.has(UI.curNode)) {
    const p = pathTo(UI.curNode);
    p.forEach((id, i) => {
      const q = IDX.Q.get(id);
      const label = q.parent_response && q.anchor && q.anchor.start > 0 ? `“${qt(q.anchor.quote)}”` : q.text;
      h += `<span class="sep">›</span><button data-crumb="${esc(id)}" class="${i === p.length - 1 ? "cur" : ""}" title="${esc(q.text)}">${esc(label)}</button>`;
    });
  }
  return `<nav class="crumbs" aria-label="Thread path">${h}</nav>`;
}
function anchorHead(g, quote, unresolved) {
  const where = g ? (g.key === "general" ? "Whole repo" : g.sec ? esc(g.sec.title) + (g.mod ? ` · <span class="modn">${esc(g.mod)}</span>` : "") : "The map") : "";
  const jump = g && g.range ? `<button data-jump="${esc(g.key)}">Show in map</button>` : "";
  return `<div class="anchor"><div class="a-sec"><span>${where}</span>${jump}</div>${quote ? `<div class="a-q${unresolved ? " unres" : ""}"${unresolved ? ` data-tip="The map was regenerated and this passage couldn't be found in it again (shown as it was asked, not attached to the nearest text)"` : ""}>“${esc(qt(quote))}”${unresolved ? " · not found in the current map" : ""}</div>` : ""}</div>`;
}
function renderThread() {
  const c = UI.compose;
  if (c && c.mode === "root" && !UI.cur) {
    const b = blockAt(c.start);
    const g = b ? { key: "", sec: b.sec, mod: b.block.type === "module" ? modLabel(b.block) : null, range: null } : null;
    return anchorHead(g, c.quote) + `<div class="empty">Ask anything about this passage. The ${agHTML("guide")} sends it to the ${agHTML("investigator")}, or to the ${agHTML("tracer")} when it asks what happens when something runs.</div>`;
  }
  const g = UI.cur && IDX.groups.get(UI.cur);
  if (!g) return `<div class="empty">Select any text in the map and choose <b>Ask</b>. Every answer can be selected and asked about in turn; follow-ups branch from the words you select.</div>`;
  const byId = claimsById();
  return crumbsHTML(g) + anchorHead(g, g.anchor?.quote, g.anchor && !g.range) + g.roots.map(id => nodeHTML(id, byId)).join("");
}
function renderNav() {
  let h = "";
  const global = D.activity.working.filter(w => !w.question && !w.stale);
  if (global.length) h += `<div class="grp"><div class="grp-h"><span>The map</span></div>${global.map(w => workHTML(w)).join("")}</div>`;
  const order = (D.map?.document?.sections || []).map(s => s.id);
  const bySec = new Map();
  for (const g of IDX.groups.values()) {
    const k = g.key === "general" ? "general" : g.sec ? g.sec.id : "unresolved";
    if (!bySec.has(k)) bySec.set(k, []);
    bySec.get(k).push(g);
  }
  const names = { general: "Whole repo", unresolved: "Not found in the current map" };
  for (const k of [...order, "general", "unresolved"]) {
    const gs = bySec.get(k);
    if (!gs) continue;
    gs.sort((a, b) => (a.range?.[0] ?? 0) - (b.range?.[0] ?? 0));
    h += `<div class="grp"><div class="grp-h"><span>${esc(names[k] || secTitle(k))}</span><span>${gs.length}</span></div>` + gs.map(g => {
      const ids = nodesIn(g);
      const first = IDX.Q.get(g.roots[0]);
      const busy = groupBusy(g);
      const flags = ids.reduce((n, id) => n + ((IDX.respOf.get(id)?.claims || []).filter(c => c.check === "not_supported").length), 0);
      const ags = [...new Set(ids.map(id => IDX.respOf.get(id)?.agent).filter(Boolean))];
      const meta = busy.length
        ? busy.map(b => avHTML(b.agent, true, "", 24)).join("") + `<span>${busy.length > 1 ? busy.length + " at work" : esc(agName(busy[0].agent)) + " at work"}</span>`
        : `<span class="ags">${ags.map(a => hgAv(a, "idle static", 20)).join("")}</span><span>${plural(ids.length, "question")}</span>${flags ? `<span class="flagn">· ${flags} not supported</span>` : ""}`;
      return `<button class="nv" data-open="${esc(g.key)}">${g.anchor ? `<div class="nv-q"><q>${esc(clip(qt(g.anchor.quote), 70))}</q>${g.mod ? ` · ${esc(g.mod)}` : ""}</div>` : ""}<div class="nv-t">${esc(first.text)}</div><div class="nv-m">${meta}</div></button>`;
    }).join("") + `</div>`;
  }
  return h || `<div class="empty">No discussions yet. Select any text in the map and choose <b>Ask</b>.</div>`;
}
function renderNotes() {
  let h = `<div class="lay-note">Your notes are a separate layer, kept in this repo's Honeyguide memory on this machine. They never change the map, and agents see a note only if you share it.</div>`;
  const notes = D.notes.notes.slice().reverse();
  if (!notes.length) return h + `<div class="empty">Select text and choose <b>Annotate</b>, or <b>Save as note</b> under an answer.</div>`;
  return h + notes.map(n => {
    const r = n.from_response ? IDX.R.get(n.from_response) : n.anchor && n.anchor.doc.startsWith("answer:") ? IDX.R.get(n.anchor.doc.slice(7)) : null;
    let src;
    if (n.from_response) src = `Saved answer · ${agHTML(r?.agent)}`;
    else if (n.anchor && n.anchor.doc.startsWith("answer:")) src = `On an answer · ${agHTML(r?.agent)}`;
    else if (n.anchor) { const rg = resolveMapAnchor(n.anchor); const b = rg && blockAt(rg[0]); src = `On the map${b ? " · " + esc(b.sec.title) + (b.block.type === "module" ? " · " + esc(modLabel(b.block)) : "") : " · not found in the current map"}`; }
    else src = "Note";
    const quote = n.from_response ? IDX.Q.get(r?.parent)?.text : n.anchor?.quote;
    const body = n.from_response ? `<div class="saved">${inlineCode(n.text.replace(/\n{2,}/g, "\n"))}</div><div class="sby">written by ${agHTML(r?.agent)}</div>` : `<div class="nb">${esc(n.text)}</div>`;
    return `<div class="note" data-note="${esc(n.id)}"><div class="src"><span>${src}</span><button data-gonote="${esc(n.id)}">Show</button></div>${quote ? `<div class="nq">“${esc(clip(qt(quote), 110))}”</div>` : ""}${body}${n.share_with_agents ? `<div class="shr">Shared with agents</div>` : ""}</div>`;
  }).join("");
}
let lastPanel = "";
function renderPanel(force) {
  document.body.classList.toggle("popen", UI.open);
  $$("#tabs button").forEach(b => { b.classList.toggle("on", b.dataset.tab === UI.tab); b.setAttribute("aria-selected", b.dataset.tab === UI.tab); });
  $("#navcount").textContent = IDX.groups.size || "";
  $("#notescount").textContent = D.notes.notes.length || "";
  $("#laycount").textContent = D.notes.notes.filter(n => n.anchor && n.anchor.doc === "map").length || "";
  const html = UI.tab === "thread" ? renderThread() : UI.tab === "nav" ? renderNav() : renderNotes();
  /* don't rebuild under the reader's selection or when nothing changed */
  const sel = getSelection();
  const selInPanel = sel.rangeCount && !sel.isCollapsed && PBODY.contains(sel.anchorNode);
  if (force || (html !== lastPanel && !selInPanel)) {
    const keep = PBODY.scrollTop;
    PBODY.innerHTML = html;
    PBODY.scrollTop = keep;
    lastPanel = html;
    playHops(PBODY);
    if (UI.tab === "thread") answerOverlays();
  }
  const others = UI.tab === "thread" && UI.cur ? D.activity.working.filter(w => !w.stale && (!w.question || IDX.groupOf.get(w.question) !== UI.cur)) : [];
  $("#pelse").innerHTML = others.length ? `<div class="lh2">Also at work</div>${others.map(w => {
    const g = w.question && IDX.groups.get(IDX.groupOf.get(w.question));
    return workHTML(w, g ? groupLabel(g) : "the map", 22);
  }).join("")}` : "";
  renderComposer();
  renderTop();
  renderMarks();
}
function render(force) { if (!IDX) return; renderPanel(force); renderHeader(); renderFigs(); }

/* ---------------------------------------------------------------- composer */
function curResponse() { const q = UI.curNode && IDX.Q.get(UI.curNode); return q && q.status === "answered" ? IDX.respOf.get(q.id) : null; }
function renderComposer() {
  const c = UI.compose, f = $("#composer");
  const show = UI.open && ((UI.tab === "thread" && (UI.cur || c)) || (c && c.mode === "note"));
  f.classList.toggle("hide", !show);
  if (!show) return;
  const mode = c ? c.mode : "follow";
  const label = mode === "note" ? "Note on" : mode === "root" ? "Ask about" : "Follow up on";
  $("#ctx").innerHTML = c && c.quote ? `<span class="lbl${mode === "note" ? " note" : ""}">${label}</span><span class="cq">“${esc(qt(c.quote))}”</span><button type="button" class="x" data-cancel aria-label="Cancel">×</button>` : "";
  $("#qp").classList.toggle("hide", !(c && c.quote && mode !== "note"));
  const cin = $("#cin"), send = $("#send");
  const resp = curResponse();
  cin.placeholder = mode === "note" ? "Write a note…" : mode === "root" ? "Ask about this passage…" : c ? "Ask about the selected words…"
    : resp ? "Ask a follow-up, or select words in an answer…" : "Select words in an answer to follow up…";
  cin.setAttribute("aria-label", mode === "note" ? "Your note" : "Your question");
  send.textContent = mode === "note" ? "Save" : "Ask";
  send.classList.toggle("note", mode === "note");
  send.disabled = !c && !resp;
  if (!$("#cfoot .cerr")) $("#cfoot").innerHTML = mode === "note"
    ? `<label><input type="checkbox" id="share"> Share with agents</label><span>A note starts no agent and never changes the map.</span>`
    : `<span>“What happens when …” questions go to the ${agHTML("tracer")}.</span>`;
}
function composerError(msg) { $("#cfoot").innerHTML = `<span class="cerr">${esc(msg)}</span>`; setTimeout(() => { $("#cfoot .cerr")?.remove(); renderComposer(); }, 5000); }
async function submit(text) {
  text = (text || "").trim();
  const c = UI.compose;
  const resp = curResponse();
  if (!c && !resp) return;
  if (!text) { $("#cin").focus(); return; }
  const anchor = c ? { doc: c.doc, revision: c.rev, quote: c.quote, start: c.start, end: c.end } : null;
  $("#send").disabled = true;
  try {
    if (c && c.mode === "note") {
      const share = !!$("#share")?.checked;
      const out = await api("/api/note", { text, anchor, share_with_agents: share });
      UI.compose = null; $("#cin").value = "";
      await refresh(["notes"]);
      if (anchor.doc === "map") UI.tab = "notes";
      toast("Saved to your notes · the map is unchanged");
      render(true);
      $(`.note[data-note="${out.note.id}"]`)?.classList.add("fresh");
      return;
    }
    let out;
    if (c && c.mode === "root") out = await api("/api/question", { text, anchor });
    else {
      const parent = c ? c.parent : resp.id;
      const r = IDX.R.get(parent);
      const a = anchor || { doc: `answer:${parent}`, revision: r.revision, quote: r.text, start: 0, end: cpLen(r.text) };
      out = await api("/api/follow-up", { text, parent_response: parent, anchor: a });
    }
    UI.compose = null; $("#cin").value = ""; autoGrow();
    await refresh(["threads"]);
    UI.cur = IDX.groupOf.get(out.question.id) || UI.cur;
    UI.curNode = out.question.id;
    UI.tab = "thread"; UI.open = true;
    applyOverlays();
    render(true);
    scrollToNode(out.question.id);
  } catch (e) {
    if (e.code === "invalid_transition") { UI.pendingRev = "?"; renderHeader(); composerError("The map changed since this page loaded. Show the new version, then ask again."); }
    else composerError(e.message);
  } finally { $("#send").disabled = false; renderComposer(); }
}
function autoGrow() { const t = $("#cin"); t.style.height = "21px"; t.style.height = Math.min(90, t.scrollHeight) + "px"; }

/* ---------------------------------------------------------------- selection toolbar: Ask, Annotate, Copy */
const TB = $("#tb");
let SEL = null;
function hideTB() { TB.style.display = "none"; SEL = null; }
/* plain-text offsets of a DOM range inside host (the map column or one answer), via the leaves */
function rangeOffsets(host, r) {
  const lfs = $$(".lf", host).filter(l => r.intersectsNode(l));
  if (!lfs.length) return null;
  const at = (leaf, node, off) => { const x = document.createRange(); x.setStart(leaf, 0); x.setEnd(node, off); return +leaf.dataset.o + cpLen(x.toString()); };
  const a = lfs[0], b = lfs[lfs.length - 1];
  let s = a.contains(r.startContainer) ? at(a, r.startContainer, r.startOffset) : +a.dataset.o;
  let e = b.contains(r.endContainer) ? at(b, r.endContainer, r.endOffset) : +b.dataset.o + cpLen(b.textContent);
  return [s, e];
}
function trimOffsets(text, s, e) {
  let q = cpSlice(text, s, e);
  const lead = cpLen(q) - cpLen(q.replace(/^\s+/, "")); s += lead;
  q = cpSlice(text, s, e);
  const trail = cpLen(q) - cpLen(q.replace(/\s+$/, "")); e -= trail;
  return e > s ? [s, e, cpSlice(text, s, e)] : null;
}
function readSelection() {
  const s = getSelection();
  if (!s.rangeCount || s.isCollapsed) return null;
  const r = s.getRangeAt(0);
  const el = r.commonAncestorContainer.nodeType === 1 ? r.commonAncestorContainer : r.commonAncestorContainer.parentElement;
  const startEl = r.startContainer.nodeType === 1 ? r.startContainer : r.startContainer.parentElement;
  if (!el || startEl.closest("input,textarea,.snip,.prev,.chip,h1,.crow,.ctx,.tb")) return null;
  const text = one(r.toString());
  if (!text) return null;
  if (COL.contains(el) && MAPTEXT) {
    const o = rangeOffsets(COL, r);
    const t = o && trimOffsets(MAPTEXT.text, o[0], o[1]);
    return t ? { kind: "map", doc: "map", rev: UI.mapRev, start: t[0], end: t[1], quote: t[2], r } : { kind: "copy", text, r };
  }
  const host = startEl.closest(".ans[data-doc]");
  if (host && host.contains(r.endContainer.nodeType === 1 ? r.endContainer : r.endContainer.parentElement)) {
    const rid = host.dataset.doc.slice(7), resp = IDX.R.get(rid);
    const o = rangeOffsets($(".atext", host), r);
    const t = o && resp && trimOffsets(resp.text, o[0], o[1]);
    if (t) return { kind: "answer", doc: host.dataset.doc, rev: resp.revision, parent: rid, start: t[0], end: t[1], quote: t[2], r };
  }
  return PBODY.contains(el) || COL.contains(el) ? { kind: "copy", text, r } : null;
}
function showTB() {
  const sel = readSelection();
  if (!sel) { hideTB(); return; }
  SEL = sel;
  $$("button", TB).forEach(b => b.classList.toggle("hide", sel.kind === "copy" && b.dataset.act !== "copy"));
  const rect = sel.r.getClientRects()[0] || sel.r.getBoundingClientRect();
  TB.style.display = "flex";
  TB.style.left = Math.min(innerWidth - TB.offsetWidth - 8, Math.max(8, rect.left + rect.width / 2 - TB.offsetWidth / 2)) + "px";
  TB.style.top = Math.max(8, rect.top - TB.offsetHeight - 10) + "px";
}
document.addEventListener("mouseup", e => { if (TB.contains(e.target) || e.target.closest?.(".grip")) return; setTimeout(showTB, 0); });
document.addEventListener("keyup", e => { if (e.shiftKey && e.key.startsWith("Arrow")) showTB(); });
TB.addEventListener("mousedown", e => e.preventDefault());
TB.addEventListener("click", e => {
  const b = e.target.closest("[data-act]");
  if (!b || !SEL) return;
  const sel = SEL;
  hideTB();
  getSelection().removeAllRanges();
  if (b.dataset.act === "copy") return copyText(sel.quote || sel.text);
  const base = { doc: sel.doc, rev: sel.rev, start: sel.start, end: sel.end, quote: sel.quote };
  if (b.dataset.act === "ask") {
    if (sel.kind === "map") {
      UI.compose = { mode: "root", ...base };
      const key = `m:${sel.start}:${sel.end}`;
      UI.cur = IDX.groups.has(key) ? key : null;
      UI.curNode = null;
    } else UI.compose = { mode: "follow", parent: sel.parent, ...base };
  } else UI.compose = { mode: "note", ...base };
  UI.open = true;
  if (UI.compose.mode === "note" && sel.kind === "map" && UI.tab === "nav") UI.tab = "notes";
  if (UI.compose.mode !== "note") UI.tab = "thread";
  applyOverlays();
  render(true);
  $("#cin").focus();
});
function copyText(t) { try { navigator.clipboard.writeText(t).catch(() => {}); } catch (e) { /* no clipboard */ } toast("Copied"); }

/* ---------------------------------------------------------------- source previews: hover a chip, click to pin */
const PREV = $("#prev"), PCACHE = new Map();
let pinned = null, hoverT = null, hideT = null;
function hiPy(line) {
  return esc(line).replace(/(#.*$)|(&quot;[^&]*?&quot;|'[^']*')|\b(def|class|return|for|while|in|if|elif|else|import|from|with|as|not|and|or|is|None|True|False|self|assert|yield|lambda|try|except|raise)\b|\b(\d+(?:\.\d+)?)\b/g,
    (m, c, s, k, n) => (c ? `<span class="t-c">${c}</span>` : s ? `<span class="t-s">${s}</span>` : k ? `<span class="t-k">${k}</span>` : `<span class="t-n">${n}</span>`));
}
function linksHTML(p) {
  const L = p.links || {};
  const gh = L.github
    ? `<a class="lk" href="${esc(L.github)}" target="_blank" rel="noopener noreferrer" data-tip="<b>GitHub</b> · ${esc(L.github_title || "")}">GitHub ${ICON.ext}</a>`
    : `<span class="lk off" tabindex="0" data-tip="<b>No GitHub link.</b> The remote isn't GitHub, or commit <code>${esc(short(p.commit))}</code> isn't on it as of your last fetch, so a link would point at code that isn't there. Open the lines in your editor instead.">GitHub · not available</span>`;
  const ed = L.vscode ? `<a class="lk" href="${esc(L.vscode)}" data-cursor="${esc(L.cursor || "")}" data-tip="Opens <code>${esc(p.path)}</code> at line ${p.start} in VS Code · ⌥-click for Cursor">${ICON.ed}Open in editor</a>` : "";
  return `<span class="src-l">${gh}${ed ? `<span class="vb"></span>${ed}` : ""}</span>`;
}
function previewHTML(p) {
  const py = /\.py$/.test(p.path);
  const rows = p.lines.map(l => `<span class="ln${l.cited ? " hl" : ""}"><i>${l.n}</i>${(py ? hiPy(l.text) : esc(l.text)) || " "}</span>`).join("");
  const changed = p.hash_matches === false ? `<div class="changed">These lines changed after the claim was checked; it is being re-checked.</div>` : "";
  return `<div class="snip"><div class="snip-h"><span>${esc(p.path)} · ${lines(p.start, p.end)}</span>${linksHTML(p)}</div>${changed}<pre>${rows}</pre></div>`;
}
async function previewFor(chip) {
  if (chip.matches(".dg-a")) {
    const ctx = hopCtxHTML(chip);
    const inner = chip.dataset.i !== undefined || chip.dataset.search ? await chipPreview(chip)
      : `<div class="snip"><div class="msg">General knowledge: nothing in this repo to show.</div></div>`;
    return inner.replace('<div class="snip">', `<div class="snip">${ctx}`);
  }
  return chipPreview(chip);
}
async function chipPreview(chip) {
  const byId = claimsById();
  const c = byId.get(chip.dataset.claim);
  if (chip.dataset.search) {
    const qs = c?.searched || [];
    return `<div class="snip"><div class="snip-h"><span>searched, not found</span></div><div class="search">${qs.length ? qs.map(q => esc(q)).join("<br>") : "no record of the searches"}<br><span>no match in the repo</span></div></div>`;
  }
  const key = `${chip.dataset.claim}:${chip.dataset.i || 0}`;
  if (!PCACHE.has(key)) {
    PCACHE.set(key, api(`/api/preview?claim=${encodeURIComponent(chip.dataset.claim)}&anchor=${chip.dataset.i || 0}&context=3`)
      .then(previewHTML).catch(e => { PCACHE.delete(key); return `<div class="snip"><div class="msg">${esc(e.message)}</div></div>`; }));
  }
  return PCACHE.get(key);
}
async function showPreview(chip) {
  const html = await previewFor(chip);
  if (!document.contains(chip) || (pinned && pinned !== chip)) return;
  PREV.innerHTML = html;
  PREV.style.display = "block";
  const r = chip.getBoundingClientRect(), w = PREV.offsetWidth, h = PREV.offsetHeight;
  if (chip.closest(".panel") && UI.open) {
    const pl = $("#panel").getBoundingClientRect().left;
    PREV.style.left = Math.max(12, pl - w - 14) + "px";
    PREV.style.top = Math.min(innerHeight - h - 12, Math.max(12, r.top + r.height / 2 - h / 2)) + "px";
    return;
  }
  PREV.style.left = Math.min(innerWidth - w - 12, Math.max(12, r.left + r.width / 2 - w / 2)) + "px";
  PREV.style.top = (r.bottom + 8 + h > innerHeight - 10 ? Math.max(8, r.top - h - 8) : r.bottom + 8) + "px";
}
function pinPreview(chip) { if (pinned === chip) { unpin(); return; } unpin(); pinned = chip; chip.classList.add("pin"); showPreview(chip); }
function unpin() { if (pinned) pinned.classList.remove("pin"); pinned = null; PREV.style.display = "none"; }

/* ---------------------------------------------------------------- tooltips and toasts */
const TIP = $("#tip");
function showTip(el, html, below) {
  if (!html) { TIP.classList.remove("on"); return; }
  TIP.innerHTML = html;
  const r = el.getBoundingClientRect();
  /* in the "Needs a look" list a tooltip opens beside the item, so it never covers the list it describes */
  if (el.closest("#ndl")) {
    TIP.style.left = Math.min(innerWidth - TIP.offsetWidth - 10, r.right + 12) + "px";
    TIP.style.top = Math.max(8, Math.min(innerHeight - TIP.offsetHeight - 8, r.top)) + "px";
    TIP.classList.add("on");
    return;
  }
  TIP.style.left = Math.min(innerWidth - TIP.offsetWidth - 10, Math.max(10, r.left + r.width / 2 - TIP.offsetWidth / 2)) + "px";
  const above = r.top - TIP.offsetHeight - 8;
  TIP.style.top = (below || above < 8 ? r.bottom + 8 : above) + "px";
  TIP.classList.add("on");
}
document.addEventListener("mouseover", e => {
  const chip = e.target.closest(".chip:not(.gone),.dg-a");
  clearTimeout(hoverT);
  if (chip || e.target.closest(".prev")) clearTimeout(hideT);
  if (chip && !pinned) hoverT = setTimeout(() => showPreview(chip), 280);
  else if (!pinned && !e.target.closest(".prev") && PREV.style.display === "block") { clearTimeout(hideT); hideT = setTimeout(() => { if (!pinned) PREV.style.display = "none"; }, 220); }
  const d = e.target.closest("[data-tip]");
  if (!d) { TIP.classList.remove("on"); return; }
  showTip(d, d.dataset.tip, !!d.closest(".prev"));
});
document.addEventListener("focusin", e => { const d = e.target.closest?.("[data-tip]"); if (d && e.target.matches(":focus-visible")) showTip(d, d.dataset.tip); else TIP.classList.remove("on"); });
let toastT = null;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("on"), 1800); }

/* ---------------------------------------------------------------- navigation */
function openGroup(key, nodeId) {
  const g = IDX.groups.get(key);
  if (!g) return;
  UI.open = true; UI.tab = "thread"; UI.cur = key;
  const keep = UI.curNode && IDX.groupOf.get(UI.curNode) === key;
  UI.curNode = nodeId || (keep ? UI.curNode : g.roots[g.roots.length - 1]);
  pathTo(UI.curNode).forEach(id => UI.closed.delete(id));
  if (UI.compose && UI.compose.mode !== "note") UI.compose = null;
  render(true);
  scrollToNode(UI.curNode);
}
function scrollToNode(id) {
  const el = id && $(`.nd[data-id="${CSS.escape(id)}"]`);
  if (!el) return;
  PBODY.scrollTop = el.getBoundingClientRect().top - PBODY.getBoundingClientRect().top + PBODY.scrollTop - 56;
}
function scrollMapTo(el, off = 200) { if (!el) return; MAIN.scrollTop += el.getBoundingClientRect().top - MAIN.getBoundingClientRect().top - off; }
function flash(el) { el.classList.remove("flashed"); void el.offsetWidth; el.classList.add("flashed"); }
function closePanel() { UI.open = false; if (UI.compose && UI.compose.mode !== "follow") UI.compose = null; applyOverlays(); render(true); }

document.addEventListener("click", e => {
  const el = e.target;
  const ed = el.closest("a[data-cursor]");
  if (ed && e.altKey && ed.dataset.cursor) { e.preventDefault(); location.href = ed.dataset.cursor; return; }
  if (el.closest(".lk")) return;
  const chip = el.closest(".chip,.dg-a");
  if (chip) { e.stopPropagation(); if (!chip.classList.contains("gone")) pinPreview(chip); return; }
  if (!el.closest(".prev")) unpin();
  if (el.closest("[data-dgclose]") || el.id === "dgov") { closeOverlay(); return; }
  const dv = el.closest("[data-dgview]");
  if (dv) { viewDiagram(dv.dataset.dgview); return; }
  const fv = el.closest("[data-fview]");
  if (fv) { const f = fv.closest(".flow"); if (fv.dataset.fview === "dg") f.dataset.force = "1"; openFlow(f.dataset.flow, fv.dataset.fview); return; }
  const ge = el.closest(".dg-e");
  if (ge) { TIP.classList.remove("on"); showCalls(ge.dataset.from, ge.dataset.to); return; }
  const gnode = el.closest(".dg-node");
  if (gnode) { TIP.classList.remove("on"); goModule(gnode.dataset.comp); return; }
  if (el.closest("[data-goflows]")) { e.preventDefault(); scrollMapTo($(`#s-${CSS.escape(flowsSection())}`), 24); return; }
  if (el.closest("#top")) { UI.open = true; if (!UI.cur && UI.tab === "thread") UI.tab = "nav"; render(true); return; }
  if (el.closest("#pclose")) { closePanel(); return; }
  const tab = el.closest("[data-tab]");
  if (tab) { UI.tab = tab.dataset.tab; if (UI.compose && UI.compose.mode !== "note") { UI.compose = null; applyOverlays(); } render(true); return; }
  const g = el.closest(".mk[data-g],.mm[data-g]");
  if (g) { if (UI.open && UI.cur === g.dataset.g && UI.tab === "thread") closePanel(); else openGroup(g.dataset.g); return; }
  const nt = el.closest(".nt[data-n],.mm.note");
  if (nt) { UI.open = true; UI.tab = "notes"; render(true); const n = $(`.note[data-note="${CSS.escape(nt.dataset.n)}"]`); if (n) { n.scrollIntoView({ block: "center" }); flash(n); } return; }
  const tog = el.closest("[data-tog]");
  if (tog) { const id = tog.dataset.tog; UI.closed.has(id) ? UI.closed.delete(id) : UI.closed.add(id); render(true); return; }
  const nd = el.closest("[data-node]");
  if (nd) { UI.closed.delete(nd.dataset.node); UI.curNode = nd.dataset.node; render(true); return; }
  const fm = el.closest(".fmk[data-go]");
  if (fm) { UI.curNode = fm.dataset.go; pathTo(UI.curNode).forEach(x => UI.closed.delete(x)); render(true); scrollToNode(UI.curNode); return; }
  const cr = el.closest("[data-crumb]");
  if (cr) { if (cr.dataset.crumb) { UI.curNode = cr.dataset.crumb; pathTo(UI.curNode).forEach(x => UI.closed.delete(x)); render(true); scrollToNode(UI.curNode); } else PBODY.scrollTop = 0; return; }
  const jp = el.closest("[data-jump]");
  if (jp) { const m = MARKS.groups.get(jp.dataset.jump); if (m) { scrollMapTo(m.els[0]); m.els.forEach(flash); } return; }
  const op = el.closest("[data-open]");
  if (op) { openGroup(op.dataset.open); const m = MARKS.groups.get(op.dataset.open); if (m) scrollMapTo(m.els[0]); return; }
  const sv = el.closest("[data-save]");
  if (sv) { saveAnswer(sv.dataset.save); return; }
  const ca = el.closest("[data-copyans]");
  if (ca) { copyText(IDX.R.get(ca.dataset.copyans)?.text || ""); return; }
  const rt = el.closest("[data-retry]");
  if (rt) { api("/api/question/retry", { id: rt.dataset.retry }).then(() => refresh(["threads"])).then(() => render(true)).catch(err => toast(err.message)); return; }
  const gn = el.closest("[data-gonote]");
  if (gn) { goNote(gn.dataset.gonote); return; }
  const rx = el.closest("[data-rfx]");
  if (rx) { UI.dismissed = rx.dataset.rfx; store.set("refreshDismissed", UI.dismissed); renderHeader(); return; }
  const rg = el.closest("[data-rfgo]");
  if (rg) { const t = $(`.claim[data-st="${rg.dataset.rfgo}"]`) || $(`.claim[data-st="rechecked"]`); if (t) { scrollMapTo(t); flash(t); } return; }
  if (el.closest("[data-reload]")) { location.reload(); return; }
  if (el.closest("[data-cancel]")) { UI.compose = null; applyOverlays(); render(true); return; }
  const qp = el.closest("#qp button");
  if (qp) { submit(qp.textContent); return; }
  if (el.closest("[data-needs-tog]")) { UI.needsOpen = !UI.needsOpen; renderNeeds(); $("#needs .nd-h")?.focus({ preventScroll: true }); return; }
  const nsA = el.closest("[data-ns]");
  if (nsA) { e.preventDefault(); goNeeds(nsA.dataset.ns, nsA.dataset.nsflow); return; }
  const gm = el.closest("[data-gomod]");
  if (gm) { e.preventDefault(); goModuleId(gm.dataset.gomod); return; }
  const mo = el.closest("[data-more]");
  if (mo) { const m = mo.closest(".mod"); setModOpen(m, !m.classList.contains("open")); layout(); return; }
  const fh = el.closest(".flow-h");
  if (fh) { const f = fh.parentElement; f.classList.toggle("open"); fh.setAttribute("aria-expanded", f.classList.contains("open")); renderFigs(); layout(); return; }
  const tocA = el.closest("#toc a");
  if (tocA) { e.preventDefault(); scrollMapTo($(tocA.getAttribute("href")), 24); return; }
});
function goNote(id) {
  const n = D.notes.notes.find(x => x.id === id);
  if (!n) return;
  const m = MARKS.notes.get(id);
  if (m) { if (!$("#laynotes").checked) { $("#laynotes").checked = true; setNotesLayer(true); } scrollMapTo(m.els[0]); m.els.forEach(flash); return; }
  const rid = n.from_response || (n.anchor && n.anchor.doc.startsWith("answer:") ? n.anchor.doc.slice(7) : null);
  const qid = rid && IDX.R.get(rid)?.parent;
  if (qid && IDX.groupOf.has(qid)) openGroup(IDX.groupOf.get(qid), qid);
}
async function saveAnswer(rid) {
  if (D.notes.notes.some(n => n.from_response === rid)) return;
  const r = IDX.R.get(rid);
  try {
    await api("/api/note", { text: r.text.slice(0, 4000), anchor: null, from_response: rid });
    await refresh(["notes"]);
    toast("Answer saved as a note · the map is unchanged");
    render(true);
  } catch (e) { toast(e.message); }
}
$("#composer").addEventListener("submit", e => { e.preventDefault(); submit($("#cin").value); });
$("#cin").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit($("#cin").value); }
  if (e.key === "Escape") $("[data-cancel]")?.click();
});
$("#cin").addEventListener("input", autoGrow);
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { unpin(); hideTB(); closeOverlay(); return; }
  /* diagram arrows, pills, graph boxes and arrows are buttons: Enter or Space acts */
  if ((e.key === "Enter" || e.key === " ") && e.target.matches?.(".dg-a,.dg-e,.dg-node")) {
    e.preventDefault();
    e.target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  }
});
function setNotesLayer(on) { document.body.classList.toggle("layer-notes", on); store.set("notesLayer", on ? "1" : "0"); layout(); }
$("#laynotes").addEventListener("change", e => setNotesLayer(e.target.checked));

/* contents highlight follows the reading position */
function spy() {
  const secs = $$("section[data-sec]", COL);
  let cur = secs[0];
  for (const s of secs) if (s.getBoundingClientRect().top < 200) cur = s;
  $$("#toc a").forEach(a => a.classList.toggle("on", !!cur && a.dataset.sec === cur.dataset.sec));
}
/* a tooltip follows its element while that element holds the focus (Tab onto a not-supported claim scrolls it into
   view, and its note must stay readable); any other tooltip closes on scroll */
function tipOnScroll() {
  const f = document.activeElement;
  if (TIP.classList.contains("on") && f && f !== document.body && f.dataset?.tip && f.matches(".claim.quiet")) showTip(f, f.dataset.tip);
  else TIP.classList.remove("on");
}
MAIN.addEventListener("scroll", () => { hideTB(); tipOnScroll(); if (!pinned) PREV.style.display = "none"; spy(); }, { passive: true });
PBODY.addEventListener("scroll", () => { TIP.classList.remove("on"); }, { passive: true });

/* ---------------------------------------------------------------- theme, motion, the rail */
function setTheme(t, save) {
  document.documentElement.dataset.theme = t;
  $("#themelabel").textContent = t === "dark" ? "Light" : "Dark";
  if (save) store.set("theme", t);
  setTimeout(layout, 0);
}
$("#theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true));
const MQ = matchMedia("(prefers-color-scheme: dark)");
MQ.addEventListener("change", e => { if (!store.get("theme")) setTheme(e.matches ? "dark" : "light"); });
const RM = matchMedia("(prefers-reduced-motion: reduce)");
const setMotion = () => document.documentElement.classList.toggle("rm", RM.matches);
RM.addEventListener("change", setMotion);
function setRail(on) {
  document.documentElement.classList.toggle("rail", on);
  store.set("rail", on ? "1" : "0");
  const b = $("#railbtn");
  b.setAttribute("aria-expanded", String(!on));
  b.setAttribute("aria-label", on ? "Expand the contents" : "Collapse the contents");
  b.dataset.tip = on ? "Expand the contents" : "Collapse the contents";
  applyWidth();
  if (MAPTEXT) renderFigs();
  setTimeout(layout, 200);
}
$("#railbtn").addEventListener("click", () => setRail(!document.documentElement.classList.contains("rail")));

/* ---------------------------------------------------------------- the resizable discussion panel */
const PW = { min: 320, max: 720, def: 408 };
let want = (() => { const w = parseInt(store.get("panelWidth"), 10); return w >= PW.min && w <= PW.max ? w : PW.def; })();
/* the panel never squeezes the reading column below 560px (plus room for the margin markers) */
function maxWidth() {
  const side = document.documentElement.classList.contains("rail") ? 56 : 224;
  return Math.max(PW.min, Math.min(PW.max, innerWidth - side - 648));
}
function applyWidth() {
  const w = Math.max(PW.min, Math.min(want, maxWidth()));
  document.documentElement.style.setProperty("--pw", w + "px");
  const g = $("#grip");
  g.setAttribute("aria-valuenow", String(w));
  g.setAttribute("aria-valuemax", String(maxWidth()));
  g.setAttribute("aria-valuetext", `${w} pixels wide`);
  return w;
}
function setWant(w, save = true) { want = Math.max(PW.min, Math.min(PW.max, Math.round(w))); applyWidth(); if (save) store.set("panelWidth", String(want)); renderFigs(); layout(); }
$("#grip").addEventListener("pointerdown", e => {
  e.preventDefault();
  const grip = e.currentTarget;
  grip.setPointerCapture(e.pointerId);
  document.body.classList.add("resizing");
  const move = ev => { want = Math.max(PW.min, Math.min(PW.max, innerWidth - ev.clientX)); applyWidth(); layout(); };
  const up = () => { grip.removeEventListener("pointermove", move); renderFigs(); grip.removeEventListener("pointerup", up); document.body.classList.remove("resizing"); setWant(Math.min(want, maxWidth())); };
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", up);
});
$("#grip").addEventListener("dblclick", () => { setWant(PW.def); toast(`Panel width reset to ${PW.def}px`); });
$("#grip").addEventListener("keydown", e => {
  const step = e.shiftKey ? 64 : 16, now = applyWidth();
  const to = { ArrowLeft: now + step, ArrowRight: now - step, Home: PW.min, End: maxWidth() }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  setWant(to);
});
addEventListener("resize", () => { applyWidth(); renderFigs(); layout(); });
MAIN.addEventListener("transitionend", layout);

/* ---------------------------------------------------------------- loading and polling */
const SNAP = {};
async function refresh(which) {
  const urls = { state: "/api/state", map: "/api/map", threads: "/api/threads", notes: "/api/notes", activity: "/api/activity" };
  const got = await Promise.all(which.map(k => api(urls[k])));
  const changed = [];
  which.forEach((k, i) => {
    const data = got[i];
    delete data.ok;
    const snap = JSON.stringify(data);
    if (snap !== SNAP[k]) { SNAP[k] = snap; D[k] = data; changed.push(k); }
  });
  if (changed.length) index();
  return changed;
}
async function poll() {
  try {
    const changed = await refresh(["state", "threads", "notes", "activity"]);
    const s = D.state;
    const want = JSON.stringify([s.map_commit, s.claims, s.freshness, s.checks]);
    if (want !== SNAP.mapKey) {
      SNAP.mapKey = want;
      const before = D.map?.document?.revision;
      const mc = await refresh(["map"]);
      const after = D.map?.document?.revision;
      if (mc.length) {
        if (!before || !after || before === after) { const top = MAIN.scrollTop; renderMap(); MAIN.scrollTop = top; changed.push("map"); }
        else UI.pendingRev = after;
      }
    }
    if (!D.map?.document && changed.includes("activity")) renderNoMap();
    if (changed.length) { applyOverlays(); render(); }
  } catch (e) {
    if (e.status === 403) { toast("This page's key is out of date; reload it."); return; }
  } finally { setTimeout(poll, document.hidden ? 8000 : 2000); }
}
async function init() {
  document.documentElement.classList.add("noanim");
  setMotion();
  setTheme(document.documentElement.dataset.theme || (MQ.matches ? "dark" : "light"));
  if (store.get("notesLayer") === "0") { $("#laynotes").checked = false; document.body.classList.remove("layer-notes"); }
  setRail(document.documentElement.classList.contains("rail"));
  $("#legend").innerHTML = `<div class="lh">Evidence, by shape</div>` + Object.entries(EV).map(([k, [name]]) => `<div><span class="sym"><span class="dot ev-${k}"></span></span>${esc(name.toLowerCase())}</div>`).join("")
    + `<div class="gap"></div><div><span class="sym"><span class="ok">✓</span></span>checked by the Checker</div><div data-tip="On the map, a claim the Checker marked not supported keeps this mark and a faint dotted underline; hover or focus it for the Checker's note. Answers show a red &quot;not supported&quot; tag."><span class="sym"><span class="dot unsup"></span></span>not supported</div>`;
  applyWidth();
  try {
    await api("/api/visit", {});
    await refresh(["state", "map", "threads", "notes", "activity"]);
  } catch (e) {
    COL.innerHTML = `<div class="nomap"><h1>Can't reach Honeyguide</h1><p>${esc(e.message)}. Is <code>honeyguide serve</code> still running? Reload once it is.</p></div>`;
    return;
  }
  const s = D.state;
  SNAP.mapKey = JSON.stringify([s.map_commit, s.claims, s.freshness, s.checks]);
  if (D.map.document) renderMap(); else renderNoMap();
  index();
  applyOverlays();
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("q") && IDX.groupOf.has(h.get("q"))) openGroup(IDX.groupOf.get(h.get("q")), h.get("q"));
  else render(true);
  if (UI.open && UI.cur) { const m = MARKS.groups.get(UI.cur); if (m) scrollMapTo(m.els[0], 160); }
  document.fonts?.ready.then(layout);
  setTimeout(poll, 2000);
  /* the first paint arrives as it is: no panel sliding in, no transitions */
  requestAnimationFrame(() => requestAnimationFrame(() => { document.documentElement.classList.remove("noanim"); document.documentElement.dataset.ready = "1"; }));
}
init();
