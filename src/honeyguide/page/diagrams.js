/* Flow diagrams (T7.4, from mockup v3.1): (A) a swimlane sequence diagram per flow, (C) one module graph per map.
   Pure functions, no DOM: layout(model, width) -> plain geometry, render(geometry) -> an SVG string. Text width is
   estimated from character counts (mono 0.6 x size, sans 0.56 x size, deliberately generous), so the same input
   gives the same picture anywhere. Served under the page's CSP: no style attributes (classes and presentation
   attributes only), nothing fetched.

   Input is a normalized model that page.js builds from the contract's path record (docs/design/agent-contract.md,
   "Tracer path record"):
     {key, id, title, lanes: {id: {name, sub, file}}, loops: {id: label}, evNames: {evidence: name},
      hops: [{fn, a, ev (shown evidence or null), style: solid|dashed|dotted, note: [bold, text] | null, d,
              from, to, edge: [name, shape] | null, loop, claim, chip (anchor index | null), search}]}
   Every hop has a caller lane (the contract has no "from nowhere" hop): the flow starts in the first hop's caller,
   marked by a start dot on its lifeline. */
"use strict";
const HGD = (() => {
  const CW = { mono: 0.6, sans: 0.56 };
  const tw = (s, size, kind = "sans") => [...String(s)].length * size * CW[kind];
  const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const r1 = v => Math.round(v * 10) / 10;
  function wrapText(s, maxW, size) {
    const out = [];
    let cur = "";
    for (const w of String(s).split(" ")) {
      const t = cur ? cur + " " + w : w;
      if (cur && tw(t, size) > maxW) { out.push(cur); cur = w; } else cur = t;
    }
    if (cur) out.push(cur);
    return out;
  }
  /* sizes, in the SVG's own units */
  const D = { gut: 28, bar: 5, headTop: 12, headH: 46, loopW: 26, loopH: 18, frameHead: 32, fn: 12, anc: 10.5, note: 11.5, pill: 11 };
  const pillText = e => (e[0] ? e[0] + " " + e[1] : e[1]);
  const pillW = e => tw(pillText(e), D.pill, "mono") + 18;
  const noteText = n => (n[0] ? n[0] + " " + n[1] : n[1]);

  function lanesOf(M) {
    const ids = [];
    for (const h of M.hops) for (const l of [h.from, h.to]) if (l && !ids.includes(l)) ids.push(l);
    return ids.map(id => { const l = M.lanes[id] || { name: id, sub: "" }; return { id, name: l.name, sub: l.sub || "", file: l.file || null }; });
  }
  /* where a hop's data goes: back to whoever acts next ("ret"), or it stays in the callee's lane as a pill ("data") */
  function edgeOf(P, i) {
    const h = P[i];
    if (!h.edge) return null;
    const nx = P[i + 1], dest = nx ? nx.from : h.from, src = h.to;
    return dest === src ? { kind: "data", lane: src } : { kind: "ret", from: src, to: dest };
  }

  /* ------------------------------------------------------------------------------------- (A) sequence diagram */
  function layoutSeq(M, width) {
    const P = M.hops, lanes = lanesOf(M), n = lanes.length, li = {};
    lanes.forEach((l, i) => (li[l.id] = i));
    /* 1. columns: each gap between neighbouring lanes is as wide as the widest thing it has to hold */
    const need = new Array(Math.max(0, n - 1)).fill(0);
    let x0, right;
    lanes.forEach(l => (l.hw = Math.round(Math.max(tw(l.name, 12.5, "mono"), tw(l.sub, 11)) + 28)));
    x0 = Math.max(lanes[0].hw / 2 + 8, D.gut + 20);
    right = lanes[n - 1].hw / 2 + 8;
    const put = (g, v) => { if (g < 0) x0 = Math.max(x0, D.gut + v); else if (g >= n - 1) right = Math.max(right, v); else need[g] = Math.max(need[g], v); };
    for (let i = 0; i < n - 1; i++) put(i, lanes[i].hw / 2 + lanes[i + 1].hw / 2 + 24);
    const blk = h => Math.max(14 + tw(h.fn, D.fn, "mono"), 14 + tw(h.a, D.anc, "mono"));
    P.forEach((h, i) => {
      const B = blk(h), f = li[h.from], t = li[h.to];
      if (f === t) put(t, D.bar + D.loopW + 10 + B + 30);
      else put(t > f ? f : f - 1, D.bar + 10 + B + 18);
      const e = edgeOf(P, i);
      if (!e) return;
      const pw = pillW(h.edge);
      if (e.kind === "data") { const p = li[e.lane]; put(p - 1, pw / 2 + 16); put(p, pw / 2 + 16); }
      else { const a = li[e.from], b = li[e.to]; put(b < a ? a - 1 : a, pw + D.bar + 36); }
    });
    /* a loop's tag sits top-left in its frame, in the gap right of the frame's leftmost lane: reserve it */
    for (const [id, label] of Object.entries(M.loops || {})) {
      const hs = P.filter(h => h.loop === id);
      if (!hs.length) continue;
      const m = Math.min(...hs.flatMap(h => [h.from, h.to]).map(l => li[l]));
      put(m, tw("LOOP", 10) * 1.3 + 8 + tw(label, 11.5) + 2 * D.bar + 24);
    }
    const natural = x0 + need.reduce((s, v) => s + v, 0) + right;
    const share = n > 1 ? Math.max(0, width - natural) / (n - 1) : 0;
    let x = x0;
    lanes.forEach((l, i) => { l.x = Math.round(x); if (i < n - 1) x += need[i] + share; });
    const W = Math.round(Math.max(natural, width));
    const L = { key: M.key, W, lanes, items: [], frames: [], acts: [], nums: [], natural: Math.round(natural) };
    const lx = id => lanes[li[id]].x, nextX = t => (t < n - 1 ? lanes[t + 1].x : W);
    /* 2. rows: time runs down; one row per call, one per return or hand-on; a loop opens a frame with a head row */
    const headB = D.headTop + D.headH;
    let y = headB + 34, frame = null;
    const open = [];
    L.start = { lane: P[0].from, x: lx(P[0].from), y: headB + 14 };
    open.push({ lane: P[0].from, y0: headB + 22 });
    const closeBar = (lane, y1) => { for (let k = open.length - 1; k >= 0; k--) if (open[k].lane === lane) { L.acts.push({ lane, x: lx(lane), y0: open[k].y0, y1 }); open.splice(k, 1); return; } };
    const span = (a, b) => { if (frame) { frame.x1 = Math.min(frame.x1, a); frame.x2 = Math.max(frame.x2, b); } };
    const closeFrame = () => { frame.y1 = y + 2; L.frames.push(frame); frame = null; y += 16; };
    P.forEach((h, i) => {
      if (h.loop && (!frame || frame.id !== h.loop)) {
        if (frame) closeFrame();
        frame = { id: h.loop, label: (M.loops || {})[h.loop] || h.loop, y0: y, x1: 1e9, x2: -1e9 };
        y += D.frameHead;
      }
      const inF = !!frame, t = li[h.to], xt = lx(h.to), B = blk(h);
      const noteLines = w => (h.note ? wrapText(noteText(h.note), w, D.note) : []);
      if (h.from === h.to) {
        const lineY = y + 12, x1 = xt + D.bar, lab = x1 + D.loopW + 10, lines = noteLines(nextX(t) - D.bar - lab - 30);
        L.items.push({ kind: "self", hop: i, x1, y: lineY, lx: lab, lines, inF });
        span(xt - 30, Math.max(lab + B, ...lines.map(s => lab + 14 + tw(s, D.note))) + 12);
        L.nums.push({ n: i + 1, y: lineY });
        y = lineY + Math.max(D.loopH + 4, 22 + lines.length * 15) + 14;
      } else {
        const f = li[h.from], xf = lx(h.from), dir = t > f ? 1 : -1, lineY = y + 22, x1 = xf + dir * D.bar, x2 = xt - dir * D.bar;
        /* a note wraps inside the gap beside the caller, so it never runs across another lane's lifeline */
        const gapEnd = dir > 0 ? lanes[f + 1].x - D.bar - 14 : lanes[f - 1].x + D.bar + 14;
        const lab = dir > 0 ? x1 + 10 : x1 - 10 - B, lines = noteLines(Math.abs(gapEnd - (lab + 13)));
        L.items.push({ kind: "call", hop: i, x1, x2, y: lineY, lx: lab, lines, inF });
        span(Math.min(xf, xt) - 30, Math.max(xf, xt) + 30);
        open.push({ lane: h.to, y0: lineY - 4 });
        L.nums.push({ n: i + 1, y: lineY });
        y = lineY + 18 + lines.length * 15 + 14;
      }
      const e = edgeOf(P, i), inE = !!frame;
      if (e && e.kind === "data") {
        const lineY = y + 12, pw = pillW(h.edge), px = lx(e.lane) - pw / 2;
        L.items.push({ kind: "data", hop: i, lane: e.lane, x: px, w: pw, y: lineY, inF: inE });
        span(px - 8, px + pw + 8);
        y = lineY + 26;
      } else if (e) {
        const a = li[e.from], b = li[e.to], xa = lx(e.from), xb = lx(e.to), dir = b > a ? 1 : -1, lineY = y + 12, pw = pillW(h.edge);
        const x1 = xa + dir * D.bar, x2 = xb - dir * D.bar, px = dir < 0 ? x1 - 12 - pw : x1 + 12;
        L.items.push({ kind: "ret", hop: i, x1, x2, y: lineY, px, pw, inF: inE });
        span(Math.min(xa, xb) - 30, Math.max(xa, xb) + 30);
        closeBar(e.from, lineY + 4);
        y = lineY + 26;
      }
      if (h.from !== h.to && !(e && e.kind === "ret") && P[i + 1]?.from !== h.to) {
        const it = L.items.find(x => x.hop === i && x.kind === "call");
        closeBar(h.to, Math.max(it.y + 20, y - 12));
      }
      if (frame && P[i + 1]?.loop !== frame.id) closeFrame();
    });
    const yEnd = y + 4;
    while (open.length) { const o = open.pop(); L.acts.push({ lane: o.lane, x: lx(o.lane), y0: o.y0, y1: yEnd - 6 }); }
    L.headB = headB;
    L.yEnd = yEnd;
    /* 3. each loop tag goes in the frame's head row, in the first gap between lifelines wide enough for it */
    for (const fr of L.frames) {
      const tagW = tw("LOOP", 10) * 1.3 + 8 + tw(fr.label, 11.5);
      const xs = lanes.map(l => l.x).filter(v => v > fr.x1 && v < fr.x2).sort((a, b) => a - b);
      const cuts = [fr.x1, ...xs.flatMap(v => [v - D.bar, v + D.bar]), fr.x2];
      let at = null;
      for (let k = 0; k < cuts.length; k += 2) if (cuts[k + 1] - cuts[k] >= tagW + 20) { at = cuts[k] + 10; break; }
      fr.tag = { x: at === null ? fr.x1 + 10 : at, y: fr.y0 + 20, w: tagW, opaque: at === null };
    }
    /* 4. key: only the line styles and evidence shapes this diagram uses */
    const used = new Set(P.map(h => h.style)), keys = [];
    if (used.has("solid")) keys.push({ k: "solid", t: "call: read in source or seen at runtime" });
    if (used.has("dashed")) keys.push({ k: "dashed", t: "call, inferred: neither read nor seen at runtime" });
    if (used.has("dotted")) keys.push({ k: "dotted", t: "call into a trace blind spot" });
    if (L.items.some(it => it.kind === "ret")) keys.push({ k: "ret", t: "return, with its data" });
    if (L.items.some(it => it.kind === "data")) keys.push({ k: "data", t: "data handed to the next call" });
    if (L.frames.length) keys.push({ k: "frame", t: "repeats" });
    const evs = [...new Set(P.map(h => h.ev))].map(ev => ({ k: "ev", ev, t: ev ? (M.evNames || {})[ev] || ev : "not checked yet" }));
    L.legend = flowKeys([keys, [{ k: "head", t: "EVIDENCE" }, ...evs]], W, yEnd + 30);
    L.H = Math.round(L.legend.bottom + 14);
    return L;
  }
  /* key items left to right, wrapping; each group starts a new row */
  function flowKeys(groups, W, y0) {
    const out = [];
    let y = y0;
    for (const g of groups) {
      let x = D.gut;
      for (const it of g) {
        const sw = it.k === "head" ? 0 : it.k === "ev" ? 12 : it.k === "data" || it.k === "frame" ? 24 : 30;
        const w = (it.k === "head" ? tw(it.t, 10) * 1.3 : sw + 8 + tw(it.t, 11.5)) + 22;
        if (x + w > W - D.gut && x > D.gut) { x = D.gut; y += 22; }
        out.push({ ...it, x, y, sw });
        x += w;
      }
      y += 22;
    }
    return { items: out, bottom: y - 8 };
  }

  /* evidence shapes, as on the rest of the page; null = not shown yet (unchecked or stale) */
  function evSvg(ev, x, y) {
    switch (ev) {
      case "read_in_source": return `<circle class="evf1" cx="${x}" cy="${y}" r="4"/>`;
      case "asserted_by_test": return `<rect class="evf1" x="${x - 3.5}" y="${y - 3.5}" width="7" height="7" rx="1"/>`;
      case "seen_at_runtime": return `<circle class="evf1" cx="${x}" cy="${y}" r="2.2"/><circle class="evr" cx="${x}" cy="${y}" r="4.6"/>`;
      case "docs": return `<path class="evf2" d="M${x} ${y - 4.5}L${x + 4.5} ${y + 3.5}H${x - 4.5}Z"/>`;
      case "inferred": return `<circle class="evi" cx="${x}" cy="${y}" r="3.8"/>`;
      case "searched_not_found": return `<circle class="evn" cx="${x}" cy="${y}" r="4.2"/>`;
      case "general_knowledge": return `<rect class="evg" x="${x - 3.2}" y="${y - 3.2}" width="6.4" height="6.4" transform="rotate(45 ${x} ${y})"/>`;
      default: return `<circle class="evp" cx="${x}" cy="${y}" r="4"/>`;
    }
  }
  const headSvg = (x, y, dir) => `<path class="hd" d="M${x} ${y}L${x - dir * 9} ${y - 4.2}L${x - dir * 9} ${y + 4.2}Z"/>`;
  const chevSvg = (x, y, dir) => `<path class="hd" d="M${x - dir * 7} ${y - 4.2}L${x} ${y}L${x - dir * 7} ${y + 4.2}"/>`;
  const pillSvg = (x, y, w, e) => `<rect class="pill" x="${r1(x)}" y="${y - 10}" width="${r1(w)}" height="20" rx="10"/><text class="ptx" x="${r1(x + 9)}" y="${y + 4}">${e[0] ? `<tspan class="pn">${esc(e[0])}</tspan><tspan class="ps"> ${esc(e[1])}</tspan>` : `<tspan class="ps">${esc(e[1])}</tspan>`}</text>`;
  function noteSvg(t, bold, x, y, lp) {
    if (bold && t.startsWith(bold)) return `<text class="dnote halo${lp}" x="${x}" y="${y}"><tspan class="b">${esc(bold)}</tspan>${esc(t.slice(bold.length))}</text>`;
    return `<text class="dnote halo${lp}" x="${x}" y="${y}">${esc(t)}</text>`;
  }

  function renderSeq(L, M) {
    const P = M.hops;
    let s = "";
    const aria = `${M.title} Sequence diagram, ${P.length} calls across ${L.lanes.map(l => l.name).join(", ")}.`;
    for (const f of L.frames) s += `<rect class="frame" data-loop="${esc(f.id)}" x="${r1(f.x1)}" y="${f.y0}" width="${r1(f.x2 - f.x1)}" height="${f.y1 - f.y0}" rx="8"/>`;
    for (const l of L.lanes) s += `<line class="life" data-lane="${esc(l.id)}" x1="${l.x}" y1="${L.headB}" x2="${l.x}" y2="${L.yEnd}"/>`;
    for (const a of L.acts) s += `<rect class="act" x="${a.x - D.bar}" y="${a.y0}" width="${2 * D.bar}" height="${r1(a.y1 - a.y0)}" rx="1.5"/>`;
    s += `<circle class="start" cx="${L.start.x}" cy="${L.start.y}" r="4.5"><title>Where the flow starts</title></circle>`;
    for (const f of L.frames) {
      const t = f.tag;
      if (t.opaque) s += `<rect class="ftbg" x="${r1(t.x - 6)}" y="${t.y - 13}" width="${r1(t.w + 12)}" height="19" rx="4"/>`;
      s += `<text class="ftag" x="${r1(t.x)}" y="${t.y}"><tspan class="ftk">LOOP</tspan><tspan dx="8">${esc(f.label)}</tspan></text>`;
    }
    for (const l of L.lanes) s += `<g class="lane-h"><rect x="${l.x - l.hw / 2}" y="${D.headTop}" width="${l.hw}" height="${D.headH}" rx="8"/><text class="lane-n" x="${l.x}" y="${D.headTop + (l.sub ? 20 : 28)}" text-anchor="middle">${esc(l.name)}</text>${l.sub ? `<text class="lane-s" x="${l.x}" y="${D.headTop + 36}" text-anchor="middle">${esc(l.sub)}</text>` : ""}</g>`;
    for (const it of L.items) {
      const h = P[it.hop], lp = it.inF ? " lp" : "";
      const at = `data-key="${esc(M.key)}" data-hop="${it.hop}" data-claim="${esc(h.claim)}"${h.chip !== null && h.chip !== undefined ? ` data-i="${h.chip}"` : ""}${h.search ? ` data-search="1"` : ""} data-ev="${esc(h.ev || "")}" data-style="${h.style}"${h.loop ? ` data-loop="${esc(h.loop)}"` : ""} tabindex="0" role="button"`;
      if (it.kind === "call" || it.kind === "self") {
        const lab = it.lx + 13;
        let g = "", hit;
        if (it.kind === "call") {
          const dir = it.x2 > it.x1 ? 1 : -1;
          g += `<line class="ln" x1="${it.x1}" y1="${it.y}" x2="${it.x2 - dir * 8}" y2="${it.y}"/>` + headSvg(it.x2, it.y, dir);
          g += evSvg(h.ev, r1(it.lx + 4), it.y - 12) + `<text class="fn halo${lp}" x="${r1(lab)}" y="${it.y - 8}">${esc(h.fn)}</text><text class="anc halo${lp}" x="${r1(lab)}" y="${it.y + 15}">${esc(h.a)}</text>`;
          it.lines.forEach((t, k) => (g += noteSvg(t, h.note[0], r1(lab), it.y + 31 + k * 15, lp)));
          const xa = Math.min(it.x1, it.x2, it.lx) - 4, xb = Math.max(it.x1, it.x2, lab + Math.max(tw(h.fn, D.fn, "mono"), tw(h.a, D.anc, "mono"))) + 2;
          hit = [xa, it.y - 24, xb - xa, 40 + it.lines.length * 15];
        } else {
          const x = it.x1, y = it.y, w = D.loopW, hh = D.loopH;
          g += `<path class="ln" d="M${x} ${y}H${x + w}V${y + hh}H${x + 8}"/>` + headSvg(x, y + hh, -1);
          g += evSvg(h.ev, r1(it.lx + 4), y + 2) + `<text class="fn halo${lp}" x="${r1(lab)}" y="${y + 6}">${esc(h.fn)}</text><text class="anc halo${lp}" x="${r1(lab)}" y="${y + 21}">${esc(h.a)}</text>`;
          it.lines.forEach((t, k) => (g += noteSvg(t, h.note[0], r1(lab), y + 37 + k * 15, lp)));
          const wmax = Math.max(tw(h.fn, D.fn, "mono"), tw(h.a, D.anc, "mono"), ...it.lines.map(t => tw(t, D.note)));
          hit = [x - 2, y - 10, it.lx + 13 + wmax - x + 6, Math.max(hh, 26 + it.lines.length * 15) + 12];
        }
        s += `<g class="dg-a k-call s-${h.style}" data-kind="call" ${at} aria-label="Hop ${it.hop + 1}: ${esc(h.fn)}${h.a ? ", " + esc(h.a) : ""}"><rect class="hit" x="${r1(hit[0])}" y="${hit[1]}" width="${r1(hit[2])}" height="${hit[3]}" rx="6"/>${g}</g>`;
      } else if (it.kind === "ret") {
        const dir = it.x2 > it.x1 ? 1 : -1, st = h.style === "dotted" ? "dotted" : "solid";
        s += `<g class="dg-a k-ret s-${st}" data-kind="ret" ${at} aria-label="Hop ${it.hop + 1} returns ${esc(pillText(h.edge))}"><rect class="hit" x="${Math.min(it.x1, it.x2) - 2}" y="${it.y - 12}" width="${Math.abs(it.x2 - it.x1) + 4}" height="24" rx="6"/><line class="ln" x1="${it.x1}" y1="${it.y}" x2="${it.x2 - dir}" y2="${it.y}"/>${chevSvg(it.x2, it.y, dir)}${pillSvg(it.px, it.y, it.pw, h.edge)}</g>`;
      } else {
        s += `<g class="dg-a k-data" data-kind="data" data-lane="${esc(it.lane)}" ${at} aria-label="Hop ${it.hop + 1} hands on ${esc(pillText(h.edge))}"><rect class="hit" x="${r1(it.x)}" y="${it.y - 11}" width="${r1(it.w)}" height="22" rx="10"/>${pillSvg(it.x, it.y, it.w, h.edge)}</g>`;
      }
    }
    for (const n of L.nums) s += `<text class="num" x="${D.gut - 16}" y="${n.y + 4}">${n.n}</text>`;
    s += `<g class="dg-key"><line class="sep" x1="${D.gut - 16}" y1="${L.yEnd + 12}" x2="${L.W - D.gut + 16}" y2="${L.yEnd + 12}"/>${keysSvg(L.legend.items)}</g>`;
    return `<svg class="dg dg-seq" data-key="${esc(M.key)}" data-natural="${L.natural}" viewBox="0 0 ${L.W} ${L.H}" width="${L.W}" height="${L.H}" role="group" aria-label="${esc(aria)}">${s}</svg>`;
  }
  function keysSvg(items) {
    let s = "";
    for (const it of items) {
      const y = it.y, x = it.x;
      if (it.k === "head") { s += `<text class="lgh" x="${x}" y="${y + 4}">${esc(it.t)}</text>`; continue; }
      if (it.k === "ev") s += evSvg(it.ev, x + 6, y);
      else if (it.k === "data") s += `<rect class="pill" x="${x}" y="${y - 7}" width="24" height="14" rx="7"/>`;
      else if (it.k === "frame") s += `<rect class="frame" x="${x}" y="${y - 7}" width="24" height="14" rx="4"/>`;
      else if (it.k === "ret") s += `<g class="k-ret"><line class="ln" x1="${x + 30}" y1="${y}" x2="${x + 1}" y2="${y}"/>${chevSvg(x, y, -1)}</g>`;
      else s += `<g class="s-${it.k}"><line class="ln" x1="${x}" y1="${y}" x2="${x + 22}" y2="${y}"/>${headSvg(x + 30, y, 1)}</g>`;
      s += `<text class="lgt" x="${r1(x + it.sw + 8)}" y="${y + 4}">${esc(it.t)}</text>`;
    }
    return s;
  }

  /* ------------------------------------------------------------------------------------------ (C) module graph */
  /* files: [{file, role, entry, module}] (the Modules section, plus lane files without a module block); flows:
     sequence models. Edges = calls between two different files (lanes with a path) across the flows. */
  function graphModel(flows, files) {
    const edges = new Map(), starts = [];
    for (const M of flows) {
      const fileOf = id => (M.lanes[id] || {}).file || null;
      if (M.hops.length) {
        const f0 = fileOf(M.hops[0].from);
        if (f0) starts.push({ file: f0, label: M.startLabel || "", flow: M.key });
      }
      M.hops.forEach((h, i) => {
        const a = fileOf(h.from), b = fileOf(h.to);
        if (!a || !b || a === b) return;
        const k = a + ">" + b;
        if (!edges.has(k)) edges.set(k, { from: a, to: b, calls: [] });
        edges.get(k).calls.push({ fn: h.fn, flow: M.key, title: M.title, hop: i });
      });
    }
    const all = [...files];
    for (const x of [...starts.map(s => s.file), ...[...edges.values()].flatMap(e => [e.from, e.to])])
      if (!all.some(f => f.file === x)) all.push({ file: x, role: "", entry: false, module: null });
    return { edges: [...edges.values()], starts, files: all, flows: flows.length };
  }
  const PORT = 40;   /* vertical distance between two lines arriving at one box: a label, its gap, and a label height to spare */
  function layoutGraph(GM, width) {
    const E = GM.edges, info = Object.fromEntries(GM.files.map(f => [f.file, f]));
    const inG = f => E.some(e => e.from === f || e.to === f) || GM.starts.some(s => s.file === f);
    const order = [...GM.starts.map(s => s.file), ...E.flatMap(e => [e.from, e.to])], first = f => order.indexOf(f);
    const layer = {}, onStack = new Set();
    const lay = f => {
      if (layer[f] === undefined) {
        onStack.add(f);
        const p = E.filter(e => e.to === f && !onStack.has(e.from)).map(e => e.from);   /* a cycle counts once */
        layer[f] = p.length ? 1 + Math.max(...p.map(lay)) : 0;
        onStack.delete(f);
      }
      return layer[f];
    };
    const files = GM.files.map(f => f.file).filter(inG);
    files.forEach(lay);
    const nL = Math.max(...files.map(f => layer[f])) + 1, cols = [...Array(nL)].map(() => []);
    files.forEach(f => cols[layer[f]].push(f));
    cols[0].sort((a, b) => first(a) - first(b));
    for (let k = 1; k < nL; k++) {
      const bc = f => { const p = E.filter(e => e.to === f).map(e => cols[layer[e.from]].indexOf(e.from)); return p.length ? p.reduce((s, v) => s + v, 0) / p.length : 0; };
      cols[k].sort((a, b) => bc(a) - bc(b) || first(a) - first(b));
    }
    const iso = GM.files.map(f => f.file).filter(f => !inG(f));
    const roleOf = f => (info[f].role || "") + (inG(f) ? "" : (info[f].role ? " · " : "") + "in no traced flow");
    const N = {};
    const tagW = tw("ENTRY POINT", 9.5) * 1.3 + 14;
    for (const f of [...files, ...iso]) {
      const ins = E.filter(e => e.to === f).length, entry = !!info[f].entry;
      N[f] = { id: f, role: roleOf(f), entry, iso: !inG(f), ins, module: info[f].module,
        w: Math.max(tw(f, 13, "mono") + (entry ? tagW + 10 : 0), tw(roleOf(f), 12)) + 28, h: Math.max(54, PORT * Math.max(0, ins - 1) + 40) };
    }
    const big = cols.reduce((b, c, k) => (c.length > cols[b].length ? k : b), 0);
    const colW = cols.map((c, k) => Math.max(...c.map(f => N[f].w), ...(k === big ? iso.map(f => N[f].w) : [])));
    const startW = Math.max(0, ...GM.starts.map(s => tw(s.label, 11.5, "mono") + 42));
    const cntW = tw("99 calls", 11) + 4;
    const gapNeed = k => { const src = cols[k].filter(f => E.some(e => e.from === f)); return 26 + 22 * Math.max(0, src.length - 1) + 16 + cntW + 24; };
    const natural = startW + 12 + colW.reduce((s, v) => s + v, 0) + cols.slice(0, -1).reduce((s, _, k) => s + Math.max(150, gapNeed(k)), 0) + 20;
    const extra = Math.max(0, width - natural), grow = nL > 1 ? Math.min(extra, 120 * (nL - 1)) / (nL - 1) : 0, pad = (extra - grow * (nL - 1)) / 2;
    let x = pad + startW + 12;
    const colX = [];
    cols.forEach((c, k) => { colX.push(x); c.forEach(f => { N[f].w = colW[k]; N[f].x = x; }); x += colW[k] + (k < nL - 1 ? Math.max(150, gapNeed(k)) + grow : 0); });
    /* rows: the tallest column stacks; the others centre on the median of the ports their lines use */
    let y = 18;
    cols[big].forEach(f => { N[f].y = y; y += N[f].h + 22; });
    const insOf = t => E.filter(e => e.to === t).sort((a, b) => first(a.from) - first(b.from));
    const portY = (t, from) => { const ins = insOf(t), k = ins.findIndex(e => e.from === from); return N[t].y + N[t].h / 2 + (k - (ins.length - 1) / 2) * PORT; };
    const med = a => { a = [...a].sort((p, q) => p - q); const m = a.length >> 1; return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2; };
    cols.forEach((c, k) => {
      if (k === big) return;
      let prevB = -1e9;
      c.forEach(f => {
        const ys = [...E.filter(e => e.from === f && layer[e.to] === big).map(e => portY(e.to, f)), ...E.filter(e => e.to === f && layer[e.from] === big).map(e => N[e.from].y + N[e.from].h / 2)];
        const want = ys.length ? med(ys) - N[f].h / 2 : 18;
        N[f].y = Math.round(Math.max(want, prevB + 22, 18));
        prevB = N[f].y + N[f].h;
      });
    });
    let bottom = Math.max(...files.map(f => N[f].y + N[f].h));
    iso.forEach(f => { N[f].x = colX[big]; N[f].w = colW[big]; N[f].y = bottom + 30; bottom = N[f].y + N[f].h; });
    /* edges: one port per incoming line on the target's left side; one vertical bus per source */
    const edges = [];
    for (const t of files) insOf(t).forEach((e, k, ins) => edges.push({ ...e, py: Math.round(portY(t, e.from)), k, m: ins.length }));
    const buses = [];
    cols.forEach((c, k) => {
      const src = c.filter(f => E.some(e => e.from === f)).sort((a, b) => N[a].y - N[b].y);
      src.forEach((f, j) => {
        const bx = Math.round(colX[k] + colW[k] + 26 + 22 * j), sy = Math.round(N[f].y + N[f].h / 2), mine = edges.filter(e => e.from === f);
        buses.push({ from: f, bx, sy, x0: N[f].x + N[f].w, y0: Math.min(sy, ...mine.map(e => e.py)), y1: Math.max(sy, ...mine.map(e => e.py)) });
        mine.forEach(e => (e.bx = bx));
      });
    });
    /* each count label sits just above its own drop, right-aligned before the arrowhead: drops into one box are
       PORT apart, so a label is 3px from its own line and more than a label height from any other */
    for (const e of edges) {
      const c = e.calls.length, w = 1.5 * c, xe = N[e.to].x - 2;
      e.w = w; e.xe = xe;
      e.label = `${c} call${c > 1 ? "s" : ""}`;
      e.ly = r1(e.py - w / 2 - 5);
      e.lx = xe - 14;
    }
    const st0 = GM.starts.filter((s, i, a) => a.findIndex(t => t.file === s.file) === i);
    const sx = Math.min(...st0.map(s => N[s.file].x - tw(s.label, 11.5, "mono") - 34));
    const starts = st0.map(s => ({ ...s, x1: sx, y: Math.round(N[s.file].y + N[s.file].h / 2) }));
    const W = Math.round(Math.max(natural, width)), keyY = bottom + 34;
    const keys = [{ k: "start", t: "where a traced flow starts" }];
    [...new Set(E.map(e => e.calls.length))].sort((a, b) => a - b).forEach(c => keys.push({ k: "w", c, t: `${c} call${c > 1 ? "s" : ""}` }));
    return { W, H: keyY + 20, N, files, iso, edges, buses, starts, keyY, keys, natural: Math.round(natural), flows: GM.flows };
  }
  function renderGraph(G) {
    let s = "";
    for (const b of G.buses) s += `<path class="gw gbus" data-from="${esc(b.from)}" stroke-width="1.5" d="M${b.x0} ${b.sy}H${b.bx}${b.y0 < b.y1 ? `M${b.bx} ${b.y0 - 0.75}V${b.y1 + 0.75}` : ""}"/>`;
    for (const e of G.edges) {
      const c = e.calls.length, w = e.w, xe = e.xe;
      const tip = `<b>${esc(e.from)} calls ${esc(e.to)}</b> · ${e.label} in the traced flows<br>` + e.calls.map(x => `<code>${esc(x.fn)}</code> · hop ${x.hop + 1}, ${esc(x.title)}`).join("<br>") + `<br>Click to see ${c > 1 ? "them" : "it"} in the flow diagram`;
      s += `<g class="dg-e" data-from="${esc(e.from)}" data-to="${esc(e.to)}" data-n="${c}" data-tip="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(e.from)} calls ${esc(e.to)}: ${e.label}">`
        + `<path class="hitl" d="M${e.bx} ${e.py}H${xe}"/><rect class="hit" x="${r1(e.lx - tw(e.label, 11) - 4)}" y="${r1(e.ly - 12)}" width="${r1(tw(e.label, 11) + 8)}" height="16"/>`
        + `<path class="gw gdrop" stroke-width="${w}" d="M${e.bx - 0.75} ${e.py}H${r1(xe - 9 - w)}"/><path class="gh" d="M${xe} ${e.py}L${r1(xe - 9 - w)} ${r1(e.py - 3.5 - w)}L${r1(xe - 9 - w)} ${r1(e.py + 3.5 + w)}Z"/>`
        + `<text class="gcnt halo" x="${r1(e.lx)}" y="${e.ly}" text-anchor="end">${e.label}</text></g>`;
    }
    for (const st of G.starts) {
      const xe = G.N[st.file].x - 2;
      s += `<g class="gst"><circle class="start" cx="${r1(st.x1)}" cy="${st.y}" r="4.5"/><path class="gw" stroke-width="1.5" d="M${r1(st.x1)} ${st.y}H${xe - 9}"/><path class="gh" d="M${xe} ${st.y}L${xe - 9} ${st.y - 4.2}L${xe - 9} ${st.y + 4.2}Z"/>${st.label ? `<text class="gstart halo" x="${r1(st.x1 + 10)}" y="${st.y - 8}">${esc(st.label)}</text>` : ""}</g>`;
    }
    for (const f of [...G.files, ...G.iso]) {
      const b = G.N[f];
      const tip = `<b>${esc(f)}</b>${b.role ? " · " + esc(b.role) : ""}${b.entry ? "<br>The entry point" : ""}<br>${b.module ? "Click for its module" : "No module section for this file"}`;
      s += `<g class="dg-node${b.iso ? " iso" : ""}" data-file="${esc(f)}" data-tip="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(f)}"><rect class="gbox" x="${r1(b.x)}" y="${r1(b.y)}" width="${r1(b.w)}" height="${b.h}" rx="8"/>`
        + `<text class="gname" x="${r1(b.x + 14)}" y="${r1(b.y + b.h / 2 + (b.role ? -3 : 5))}">${esc(f)}</text>${b.role ? `<text class="grole" x="${r1(b.x + 14)}" y="${r1(b.y + b.h / 2 + 14)}">${esc(b.role)}</text>` : ""}`
        + (b.entry ? `<rect class="gtagbox" x="${r1(b.x + 14 + tw(f, 13, "mono") + 10)}" y="${r1(b.y + b.h / 2 - (b.role ? 15 : 7))}" width="${r1(tw("ENTRY POINT", 9.5) * 1.3 + 12)}" height="16" rx="4"/><text class="gtag" x="${r1(b.x + 14 + tw(f, 13, "mono") + 16)}" y="${r1(b.y + b.h / 2 - (b.role ? 4 : -4))}">ENTRY POINT</text>` : "") + `</g>`;
    }
    let x = D.gut - 12;
    const y = G.keyY;
    s += `<g class="dg-key"><line class="sep" x1="${D.gut - 16}" y1="${y - 20}" x2="${G.W - D.gut + 16}" y2="${y - 20}"/>`;
    for (const k of G.keys) {
      if (k.k === "start") { s += `<circle class="start" cx="${x + 5}" cy="${y}" r="4.5"/><text class="lgt" x="${x + 16}" y="${y + 4}">${k.t}</text>`; x += 16 + tw(k.t, 11.5) + 26; }
      else { s += `<path class="gw" stroke-width="${1.5 * k.c}" d="M${x} ${y}H${x + 28}"/><text class="lgt" x="${x + 36}" y="${y + 4}">${k.t}</text>`; x += 36 + tw(k.t, 11.5) + 22; }
    }
    s += `<text class="lgt" x="${r1(x)}" y="${y + 4}">between files, counted across the ${G.flows} traced flow${G.flows === 1 ? "" : "s"}</text></g>`;
    return `<svg class="dg dg-graph" data-key="graph" data-natural="${G.natural}" viewBox="0 0 ${G.W} ${G.H}" width="${G.W}" height="${G.H}" role="group" aria-label="Module graph: ${G.files.length + G.iso.length} files and the calls between them">${s}</svg>`;
  }

  return { tw, wrapText, edgeOf, lanesOf, layoutSeq, renderSeq, graphModel, layoutGraph, renderGraph, D, PORT };
})();
