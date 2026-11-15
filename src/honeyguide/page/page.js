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
const AG = { guide: ["🧭", "Guide"], cartographer: ["🗺️", "Cartographer"], investigator: ["🔦", "Investigator"], tracer: ["🧵", "Tracer"], checker: ["✅", "Checker"] };
const agName = a => (AG[a] || ["", a || "an agent"])[1];
const agFull = a => (AG[a] ? AG[a][0] + " " + AG[a][1] : a || "an agent");
const ICON = {
  ext: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M12 9.5v3a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h3"/></svg>`,
  ed: `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 5 2.5 8l3 3M10.5 5l3 3-3 3"/></svg>`,
  ok: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="m5.5 8 1.8 1.8L10.7 6.4"/></svg>`,
  info: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"><circle cx="8" cy="8" r="6"/><path d="M8 7.2v3.6M8 5.2v.1"/></svg>`,
  rf: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M13 3.5v3h-3"/><path d="M12.6 6.5A5 5 0 1 0 13 9"/></svg>`,
  msg: `<svg class="i" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round"><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/></svg>`,
};
const LOGO = $(".brand .logo").outerHTML.replace('id="logo-eye"', 'id="logo-eye2"').replace("url(#logo-eye)", "url(#logo-eye2)");

/* ---------------------------------------------------------------- data */
const D = { state: null, map: null, threads: { questions: [], responses: [] }, notes: { notes: [] }, activity: { working: [], recent: [] } };
const UI = { open: false, tab: "thread", cur: null, curNode: null, compose: null, closed: new Set(), mapRev: null, pendingRev: null, dismissed: store.get("refreshDismissed") || "" };
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
/* the map's plain text, exactly as mapdoc.plain_text builds it, with each block's [start, end) */
function mapText(doc) {
  const parts = [], blocks = [];
  let pos = 0, first = true;
  for (const sec of doc.sections || []) {
    for (const piece of [sec.title || "", ...(sec.blocks || [])]) {
      if (!first) pos += 2;
      first = false;
      const text = typeof piece === "string" ? piece : (piece.spans || []).map(s => s.text || "").join("");
      if (typeof piece !== "string") blocks.push({ id: piece.id, start: pos, end: pos + cpLen(text), sec, block: piece });
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
/* spans (with claims) to HTML, offsets from o; ctx: "map" or "answer" */
function spansHTML(spans, o, ctx, byId) {
  let html = "", pos = o;
  for (const s of spans) {
    const t = s.text || "";
    if (s.claim) {
      const c = byId.get(s.claim);
      const st = claimState(c);
      const cls = ["claim", c?.evidence === "general_knowledge" ? "gk" : "", st.startsWith("stale") ? "stale" : "", st === "retired" ? "retired" : "",
        c?.check === "not_supported" && !st.startsWith("stale") ? "flagged" : ""].filter(Boolean).join(" ");
      html += `<span class="${cls}" data-claim="${esc(s.claim)}" data-st="${st}">${leaves(t, pos)}</span>${citeHTML(c, ctx)}`;
    } else html += leaves(t, pos);
    pos += cpLen(t);
  }
  return html;
}

/* ---------------------------------------------------------------- claims: evidence mark, chips, checker mark */
function evTip(c, extra) {
  const [name, note] = EV[c.evidence] || [c.evidence, ""];
  return `<b>${esc(name)}</b>${note ? " · " + esc(note) : ""}${extra ? " · " + extra : ""}`;
}
function chipsHTML(c, gone) {
  if (c.evidence === "searched_not_found") return `<button class="chip" data-claim="${esc(c.id)}" data-search="1">searched</button>`;
  return (c.anchors || []).map((a, i) => {
    const label = `${a.path}:${a.start === a.end ? a.start : a.start + "–" + a.end}`;
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
  let html = `<header><h1>${esc(doc.title || "Map")}</h1><p class="sub" id="sub"></p><div class="mem" id="mem"></div><div id="refresh"></div><div id="mapnew"></div><p class="hint">Select any text to ask about it or annotate it.</p></header>`;
  let bi = 0;
  for (const sec of doc.sections || []) {
    html += `<section id="s-${esc(sec.id)}" data-sec="${esc(sec.id)}"><h2>${esc(sec.title)}</h2>`;
    for (const block of sec.blocks || []) {
      const b = MAPTEXT.blocks[bi++];
      let body = spansHTML(block.spans || [], b.start, "map", byId);
      /* a retired claim's reason goes under its passage, so the sentence itself stays whole */
      const whys = [...body.matchAll(/<span class="rwhy-at" data-why="([^"]*)"><\/span>/g)].map(m => m[1]);
      body = body.replace(/<span class="rwhy-at" data-why="[^"]*"><\/span>/g, "") + whys.map(w => `<span class="rwhy">Retired: ${w}.</span>`).join("");
      const allGone = (block.spans || []).filter(x => x.claim).every(x => byId.get(x.claim)?.freshness === "retired") && (block.spans || []).some(x => x.claim);
      if (block.type === "module") {
        html += `<div class="mod" data-block="${esc(block.id)}"><div class="mod-h"><code${allGone ? ` class="gone" data-tip="Every claim about this file is retired"` : ""}>${esc(block.path)}</code></div><p class="blk">${body}</p></div>`;
      } else if (block.type === "flow") {
        const f = flows.get(block.flow);
        html += `<div class="flow" data-flow="${esc(block.flow)}" data-block="${esc(block.id)}"><button class="flow-h" aria-expanded="false"><span class="fq">${esc(f ? f.title : block.flow)}<span class="fcar">▸</span></span><span class="meta"><span class="em">🧵</span>Tracer · ${plural(f ? f.hops.length : 0, "hop")}</span></button>`
          + `<p class="cap blk">${body}</p><div class="fbody">`
          + `<div class="slot" data-slot="swimlane" data-flow="${esc(block.flow)}"><b>Swimlane diagram</b> · drawn here in step 4 (T7.4)</div>`
          + (f ? pathHTML(f, byId, false) : "") + `</div></div>`;
      } else html += `<p class="blk" data-block="${esc(block.id)}">${body}</p>`;
    }
    if (sec.kind === "overview" && (doc.flows || []).length)
      html += `<div class="slot" data-slot="module-graph"><b>Module graph</b> · files and the calls between them, drawn here in step 4 (T7.4)</div>`;
    html += `</section>`;
  }
  COL.innerHTML = html;
  document.body.classList.remove("nomap-on");
  renderToc();
  index();
  renderHeader();
  applyOverlays();
}
function renderNoMap() {
  MAPTEXT = null; UI.mapRev = null;
  const carto = D.activity.working.filter(w => w.agent === "cartographer" && !w.stale);
  COL.innerHTML = `<div class="nomap">${LOGO}<h1>No map yet</h1>
    <p>Honeyguide has no map of <b>${esc(REPO_NAME)}</b> yet.</p>
    <ol><li>Open Claude Code in this repository, with the Honeyguide plugin installed.</li>
    <li>Ask it to map the repo. The 🗺️ Cartographer reads the code and saves a map in which every claim cites its lines.</li>
    <li>This page shows the map as soon as it is saved; you don't need to reload.</li></ol>
    ${carto.map(workHTML).join("")}
    <p class="quiet">Memory for this repo lives outside the checkout, in <code>~/.honeyguide/</code> (or <code>$HONEYGUIDE_HOME</code>).</p></div>`;
  $("#toc").innerHTML = "";
  $("#repo").textContent = REPO_NAME;
  document.body.classList.add("nomap-on");
}
function renderToc() {
  const doc = D.map?.document;
  if (!doc) return;
  $("#toc").innerHTML = (doc.sections || []).map(s => `<li><a href="#s-${esc(s.id)}" data-sec="${esc(s.id)}" title="${esc(s.title)}"><span class="ini" aria-hidden="true">${esc((s.title || "?").trim()[0].toUpperCase())}</span><span class="tt">${esc(s.title)}</span><span class="n"></span></a></li>`).join("");
  spy();
}
function blockAt(off) { return MAPTEXT?.blocks.find(b => off >= b.start && off < b.end) || MAPTEXT?.blocks.find(b => off <= b.end) || null; }

/* ---------------------------------------------------------------- Tracer path (map flows and panel answers) */
function pathHTML(p, byId, panel) {
  const lanes = new Map((p.lanes || []).map(l => [l.id, l]));
  const loops = new Map((p.loops || []).map(l => [l.id, l]));
  const counts = {};
  const hops = (p.hops || []).map((h, i) => {
    const c = byId.get(h.claim);
    const ev = c ? c.evidence : "inferred";
    const st = claimState(c);
    const checked = c && c.check && c.check !== "unchecked" && st !== "stale";
    counts[ev] = (counts[ev] || 0) + 1;
    const tag = i === 0 ? "entry" : i === p.hops.length - 1 ? "end" : "";
    const to = lanes.get(h.to);
    const loop = h.loop && loops.get(h.loop);
    const tr = h.trace === "unseen" ? `<span class="tr">not in the runtime trace</span>` : h.trace === "blind_spot" ? `<span class="tr">trace blind spot</span>` : "";
    const ok = panel && c?.check === "supported" && st !== "stale" ? `<span class="ok" data-tip="<b>Checked</b> · the Checker re-read the cited lines: supported">✓</span>`
      : c?.check === "not_supported" ? `<span class="flag" data-tip="<b>Not supported.</b> ${esc(c.check_note || "")}">not supported</span>` : "";
    const edgeText = h.data || h.returns;
    const edge = edgeText ? `<li class="edge"><span><b>${h.data ? "data" : "returns"}</b>${esc(edgeText)}</span></li>` : "";
    return `<li class="hop ${esc(h.trace || "")}"><span class="node ${checked || !panel ? "ev-" + esc(ev) : "pending"}" data-tip="${c ? esc(evTip(c)) : ""}"></span><div class="hop-b">`
      + `<div class="hop-t"><span class="fn">${esc(h.call)}</span>${tag ? `<span class="loop">${tag}</span>` : ""}${loop ? `<span class="loop" data-tip="Repeats: ${esc(loop.label)}">${esc(loop.label)}</span>` : ""}</div>`
      + (h.label ? `<div class="hop-d">${inlineCode(h.label)}</div>` : "")
      + `<div class="hop-l">${to ? `<span class="lane">${esc(to.label)}</span>` : ""}<span class="lab ev-${esc(ev)}">${esc((EV[ev] || [ev])[0].toLowerCase())}</span>${tr}${c ? chipsHTML(c, st === "retired") : ""}${ok}</div>`
      + `</div></li>${edge}`;
  }).join("");
  const foot = `<div class="path-foot">${Object.entries(counts).map(([ev, n]) => `<span><span class="dot ev-${esc(ev)}"></span>${n} ${esc((EV[ev] || [ev])[0].toLowerCase())}</span>`).join("")}</div>`;
  return `<ol class="path">${hops}</ol>${foot}`;
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
      groups.set(key, { key, anchor: a && a.doc === "map" ? a : null, range, sec: b?.sec || null, mod: b?.block.type === "module" ? b.block.path : null, roots: [] });
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
  const claims = allClaims();
  const mapClaims = D.map.claims || [];
  const files = new Set(mapClaims.flatMap(c => (c.anchors || []).map(a => a.path)));
  $("#sub").textContent = `Mapped by the 🗺️ Cartographer · ${plural((doc.sections || []).length, "section")} · cites ${plural(files.size, "file")}`;
  /* the same rules as memory.memory_state: behind HEAD first, then claims waiting for a re-check */
  const stale = claims.filter(c => claimState(c) === "stale").length;
  const failed = claims.filter(c => claimState(c) === "stale_flagged").length;
  const retired = mapClaims.filter(c => c.freshness === "retired").length;
  const live = mapClaims.filter(c => c.freshness !== "retired").length;
  let h;
  if (s.map_commit && s.map_commit !== s.head) {
    h = `<span class="mem-i warn">${ICON.info}</span><span data-tip="The map was saved at <code>${esc(short(s.map_commit))}</code>; HEAD is now <code>${esc(short(s.head))}</code>. A refresh re-resolves every claim against the new code.">Map at <code>${esc(short(s.map_commit))}</code> · HEAD is <code>${esc(short(s.head))}</code>: refresh pending</span>`;
  } else if (stale) {
    h = `<span class="mem-i busy"><span class="ring"></span></span><span data-tip="The code changed since these claims were checked. They are shown greyed, without their evidence mark, and not served as fact or given to agents until the Checker re-reads the new lines.">Refreshing · ${plural(stale, "claim")} being re-checked</span>`;
  } else {
    h = `<span class="mem-i">${ICON.ok}</span><span data-tip="The map is at <code>${esc(short(s.head))}</code>, which is HEAD, and no claim waits for a re-check.">Up to date at <code>${esc(short(s.head))}</code></span>`;
  }
  const parts = [stale + failed ? `${stale + failed} stale` : "", retired ? `${retired} retired` : ""].filter(Boolean);
  h += `<span class="sep">·</span><span>${plural(live, "claim")}${parts.length ? ", " + parts.join(", ") : ", every anchor resolved"}</span>`;
  /* re-checked = a verdict on a claim that had gone stale (rechecked_at, as memory.memory_state counts it) */
  const since = s.previous_visit ? claims.filter(c => c.rechecked_at && c.rechecked_at > s.previous_visit).length : 0;
  if (since) h += `<span class="sep">·</span><span class="since">${plural(since, "claim")} re-checked since your last visit</span>`;
  if (s.dirty && s.dirty.tracked) h += `<span class="sep">·</span><span data-tip="${s.dirty.tracked} uncommitted change(s) in the working tree. The map and previews read committed code only.">uncommitted changes not mapped</span>`;
  $("#mem").innerHTML = h;
  $("#repo").textContent = `${doc.title || ""} @ ${short(s.head)}`;
  /* the refresh since the last visit */
  const log = s.refresh_log || [];
  const last = log[log.length - 1];
  const show = last && (!s.previous_visit || last.at > s.previous_visit) && UI.dismissed !== last.at;
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
  const work = stale ? (checker.length ? `<div class="rf-w">${avHTML("checker", true)}<span><b>Checker</b> ${inlineCode(checker[0].status)}; not shown as fact until it finishes</span></div>`
    : `<div class="rf-w"><span>${plural(stale, "stale claim")} waiting for the ✅ Checker; not shown as fact until re-checked</span></div>`) : "";
  return `<div class="refresh" role="status"><div class="rf-h"><span class="i">${ICON.rf}</span><b>Refreshed since your last visit</b><span>· updated from <code>${esc(short(e.base))}</code> to <code>${esc(short(e.target))}</code></span><button class="x" data-rfx="${esc(e.at)}" aria-label="Dismiss">×</button></div>`
    + (btns ? `<div class="rf-c">${btns}</div>` : "") + (e.note ? `<div class="rf-n">${inlineCode(e.note)}</div>` : "") + work + `</div>`;
}

/* ---------------------------------------------------------------- agents */
const avHTML = (ag, working, tip) => `<span class="av a-${esc(ag)}${working ? " working" : ""}"${tip ? ` data-tip="${esc(tip)}"` : ""} aria-hidden="true"><span class="face">${(AG[ag] || ["•"])[0]}</span></span>`;
function workHTML(w, ctx) {
  return `<div class="work">${avHTML(w.agent, true)}<div><b>${esc(agName(w.agent))}</b>${inlineCode(w.status)}${ctx ? `<span class="wctx">· ${esc(ctx)}</span>` : ""}</div></div>`;
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
    top.innerHTML = `<span class="mini">${ags.map(a => avHTML(a, true)).join("")}</span><span>${ags.length} at work</span>`;
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
  const path = r.path ? `${pathHTML(r.path, byId, true)}<span class="asdiagram" data-tip="The swimlane diagram view arrives in step 4 (T7.4)">View as diagram</span>` : "";
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
  if (un === tot) return `<div class="chk" data-tip="Answers show at once; each claim gains its evidence mark when the Checker has re-read its lines">Not checked yet · ${plural(tot, r.path ? "hop" : "claim")} waiting for the ✅ Checker</div>`;
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
    const via = r.agent === "tracer" ? "· routed by 🧭 Guide as a flow question" : "· answer";
    const saved = D.notes.notes.some(n => n.from_response === r.id);
    body = `<div class="by">${avHTML(r.agent, false)}<span class="who">${esc(agName(r.agent))}</span><span class="via">${via}</span></div>`
      + answerHTML(q, r, byId) + checkHTML(q, r)
      + `<div class="acts"><button data-save="${esc(r.id)}" class="${saved ? "done" : ""}">${saved ? "Saved to notes ✓" : "Save as note"}</button><button data-copyans="${esc(r.id)}">Copy</button></div>`;
  } else if (q.status === "failed") {
    body = `<div class="failed">Couldn't answer: ${esc(q.error || "the agent stopped")}<button data-retry="${esc(id)}">Retry</button></div>`;
  } else if (work.length) {
    body = work.map(w => workHTML(w)).join("") + `<div class="shim w1"></div><div class="shim w2"></div>`;
  } else if (q.status === "investigating") {
    body = `<div class="work">${avHTML(q.agent || "investigator", true)}<div><b>${esc(agName(q.agent || "investigator"))}</b>is working on it</div></div><div class="shim w1"></div><div class="shim w2"></div>`;
  } else {
    body = `<div class="wait">${avHTML("guide", false)} Waiting for the 🧭 Guide. Your Claude Code session picks questions up while it runs <code>honeyguide watch</code>.</div>`;
  }
  const busy = q.status !== "answered" && q.status !== "failed";
  const meta = `${r ? agFull(r.agent) : "🧭 Guide"} · ${busy ? "working" : r ? plural((r.claims || []).length, r.path ? "hop" : "claim") : "failed"}${kids ? ` · ${plural((IDX.kids.get(id) || []).length, "follow-up")}` : ""}`;
  const onp = UI.curNode && id !== UI.curNode && pathTo(UI.curNode).includes(id);
  const closed = UI.closed.has(id);
  return `<div class="nd${closed ? " closed" : ""}${onp ? " onpath" : ""}${id === UI.curNode ? " cur" : ""}" data-id="${esc(id)}">
    <div class="nd-q"><button class="car" data-tog="${esc(id)}" aria-label="${closed ? "Expand" : "Collapse"}" aria-expanded="${!closed}">▼</button><div><button class="qt" data-node="${esc(id)}">${on}${esc(q.text)}</button><span class="meta1">${esc(meta)}</span></div></div>
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
    const g = b ? { key: "", sec: b.sec, mod: b.block.type === "module" ? b.block.path : null, range: null } : null;
    return anchorHead(g, c.quote) + `<div class="empty">Ask anything about this passage. The 🧭 Guide sends it to the 🔦 Investigator, or to the 🧵 Tracer when it asks what happens when something runs.</div>`;
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
        ? busy.map(b => avHTML(b.agent, true)).join("") + `<span>${busy.length > 1 ? busy.length + " at work" : esc(agName(busy[0].agent)) + " at work"}</span>`
        : `<span class="em">${ags.map(a => (AG[a] || [""])[0]).join(" ")}</span><span>${plural(ids.length, "question")}</span>${flags ? `<span class="flagn">· ${flags} not supported</span>` : ""}`;
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
    if (n.from_response) src = `Saved answer · ${esc(agFull(r?.agent))}`;
    else if (n.anchor && n.anchor.doc.startsWith("answer:")) src = `On an answer · ${esc(agFull(r?.agent))}`;
    else if (n.anchor) { const rg = resolveMapAnchor(n.anchor); const b = rg && blockAt(rg[0]); src = `On the map${b ? " · " + esc(b.sec.title) + (b.block.type === "module" ? " · " + esc(b.block.path) : "") : " · not found in the current map"}`; }
    else src = "Note";
    const quote = n.from_response ? IDX.Q.get(r?.parent)?.text : n.anchor?.quote;
    const body = n.from_response ? `<div class="saved">${inlineCode(n.text.replace(/\n{2,}/g, "\n"))}</div><div class="sby">written by ${esc(agFull(r?.agent))}</div>` : `<div class="nb">${esc(n.text)}</div>`;
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
    if (UI.tab === "thread") answerOverlays();
  }
  const others = UI.tab === "thread" && UI.cur ? D.activity.working.filter(w => !w.stale && (!w.question || IDX.groupOf.get(w.question) !== UI.cur)) : [];
  $("#pelse").innerHTML = others.length ? `<div class="lh2">Also at work</div>${others.map(w => {
    const g = w.question && IDX.groups.get(IDX.groupOf.get(w.question));
    return workHTML(w, g ? groupLabel(g) : "the map");
  }).join("")}` : "";
  renderComposer();
  renderTop();
  renderMarks();
}
function render(force) { if (!IDX) return; renderPanel(force); renderHeader(); }

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
    : `<span>“What happens when …” questions go to the 🧵 Tracer.</span>`;
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
  const byId = claimsById();
  const c = byId.get(chip.dataset.claim);
  if (chip.dataset.search) {
    const qs = c?.searched || [];
    return `<div class="snip"><div class="snip-h"><span>searched, not found</span></div><div class="search">${qs.length ? qs.map(q => esc(q)).join("<br>") : "no record of the searches"}<br><span>no match in the repo</span></div></div>`;
  }
  const key = `${chip.dataset.claim}:${chip.dataset.i}`;
  if (!PCACHE.has(key)) {
    PCACHE.set(key, api(`/api/preview?claim=${encodeURIComponent(chip.dataset.claim)}&anchor=${chip.dataset.i}&context=3`)
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
  TIP.style.left = Math.min(innerWidth - TIP.offsetWidth - 10, Math.max(10, r.left + r.width / 2 - TIP.offsetWidth / 2)) + "px";
  const above = r.top - TIP.offsetHeight - 8;
  TIP.style.top = (below || above < 8 ? r.bottom + 8 : above) + "px";
  TIP.classList.add("on");
}
document.addEventListener("mouseover", e => {
  const chip = e.target.closest(".chip:not(.gone)");
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
  const chip = el.closest(".chip");
  if (chip) { e.stopPropagation(); if (!chip.classList.contains("gone")) pinPreview(chip); return; }
  if (!el.closest(".prev")) unpin();
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
  const fh = el.closest(".flow-h");
  if (fh) { const f = fh.parentElement; f.classList.toggle("open"); fh.setAttribute("aria-expanded", f.classList.contains("open")); layout(); return; }
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
document.addEventListener("keydown", e => { if (e.key === "Escape") { unpin(); hideTB(); } });
function setNotesLayer(on) { document.body.classList.toggle("layer-notes", on); store.set("notesLayer", on ? "1" : "0"); layout(); }
$("#laynotes").addEventListener("change", e => setNotesLayer(e.target.checked));

/* contents highlight follows the reading position */
function spy() {
  const secs = $$("section[data-sec]", COL);
  let cur = secs[0];
  for (const s of secs) if (s.getBoundingClientRect().top < 200) cur = s;
  $$("#toc a").forEach(a => a.classList.toggle("on", !!cur && a.dataset.sec === cur.dataset.sec));
}
MAIN.addEventListener("scroll", () => { hideTB(); TIP.classList.remove("on"); if (!pinned) PREV.style.display = "none"; spy(); }, { passive: true });
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
function setWant(w, save = true) { want = Math.max(PW.min, Math.min(PW.max, Math.round(w))); applyWidth(); if (save) store.set("panelWidth", String(want)); layout(); }
$("#grip").addEventListener("pointerdown", e => {
  e.preventDefault();
  const grip = e.currentTarget;
  grip.setPointerCapture(e.pointerId);
  document.body.classList.add("resizing");
  const move = ev => { want = Math.max(PW.min, Math.min(PW.max, innerWidth - ev.clientX)); applyWidth(); layout(); };
  const up = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); document.body.classList.remove("resizing"); setWant(Math.min(want, maxWidth())); };
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
addEventListener("resize", () => { applyWidth(); layout(); });
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
    + `<div class="gap"></div><div><span class="sym"><span class="ok">✓</span></span>checked by the Checker</div><div><span class="flag">not supported</span></div>`;
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
