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
    if (used.has("dotted")) keys.push({ k: "dotted", t: M.traced === false ? "call into code a Python trace can't see (not run)" : "call into a trace blind spot" });
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
  /* T7.15: one box per Modules component. comps: [{id, name, role, files, entry, module, title}] (a component's files
     may be directories, "tasks/"); a map whose modules are single files gives one component per file. resolver(comps)
     maps a repo path to its component: the component listing the file, else the one whose directory holds it (the
     deepest), else null. */
  function resolver(comps) {
    const exact = new Map(), dirs = [];
    for (const c of comps) for (const f of c.files || []) {
      if (f.endsWith("/")) dirs.push([f, c]);
      else { if (!exact.has(f)) exact.set(f, c); dirs.push([f + "/", c]); }
    }
    dirs.sort((a, b) => b[0].length - a[0].length);
    return path => (!path ? null : exact.get(path) || (dirs.find(([d]) => path.startsWith(d)) || [])[1] || null);
  }
  /* flows: sequence models. Edges = calls between two different components across the flows (calls inside one
     component excluded); a lane whose file no component covers becomes its own box, named by its file. */
  function graphModel(flows, comps) {
    const all = comps.map(c => ({ ...c, files: [...(c.files || [])] }));
    const known = resolver(all), extra = new Map();
    const compOf = path => {
      if (!path) return null;
      const c = known(path);
      if (c) return c.id;
      if (!extra.has(path)) extra.set(path, { id: "file:" + path, name: path, role: "", files: [path], entry: false, module: null, title: "" });
      return extra.get(path).id;
    };
    const edges = new Map(), starts = [];
    for (const M of flows) {
      const compOfLane = id => compOf((M.lanes[id] || {}).file || null);
      if (M.hops.length) {
        const c0 = compOfLane(M.hops[0].from);
        if (c0) starts.push({ comp: c0, label: M.startLabel || "", flow: M.key });
      }
      M.hops.forEach((h, i) => {
        const a = compOfLane(h.from), b = compOfLane(h.to);
        if (!a || !b || a === b) return;
        const k = a + ">" + b;
        if (!edges.has(k)) edges.set(k, { from: a, to: b, calls: [] });
        edges.get(k).calls.push({ fn: h.fn, flow: M.key, title: M.title, hop: i });
      });
    }
    const comps2 = [...all, ...extra.values()];
    const E = [...edges.values()];
    const inG = id => E.some(e => e.from === id || e.to === id) || starts.some(s => s.comp === id);
    return { edges: E, starts, comps: comps2, iso: comps2.filter(c => !inG(c.id)).map(c => c.id), flows: flows.length };
  }
  /* a component's name in its box: its first file's name (a directory keeps its path), "+N" for the rest; every
     path is listed on hover */
  const base = f => (f.endsWith("/") ? f : f.split("/").pop());
  const compName = c => c.name || base((c.files || [])[0] || c.id) + ((c.files || []).length > 1 ? ` +${c.files.length - 1}` : "");
  const ROLE_W = 176;   /* a box's role wraps at this width, onto at most two lines */
  function roleLines(role) {
    if (!role) return [];
    const ls = wrapText(role, ROLE_W, 12);
    if (ls.length <= 2) return ls;
    let last = ls.slice(1).join(" ");
    while (last && tw(last + "…", 12) > ROLE_W) last = last.slice(0, -1);
    return [ls[0], last.trimEnd() + "…"];
  }
  const MINGAP = 120;   /* the least space between two layers of boxes */
  const PORT = 40;   /* vertical distance between two lines arriving at one box: a label, its gap, and a label height to spare */
  function layoutGraphLR(GM, width) {
    const E = GM.edges, info = Object.fromEntries(GM.comps.map(c => [c.id, c]));
    const inG = f => E.some(e => e.from === f || e.to === f) || GM.starts.some(s => s.comp === f);
    const order = [...GM.starts.map(s => s.comp), ...E.flatMap(e => [e.from, e.to])], first = f => order.indexOf(f);
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
    const files = GM.comps.map(c => c.id).filter(inG);
    files.forEach(lay);
    const nL = Math.max(...files.map(f => layer[f])) + 1, cols = [...Array(nL)].map(() => []);
    files.forEach(f => cols[layer[f]].push(f));
    cols[0].sort((a, b) => first(a) - first(b));
    for (let k = 1; k < nL; k++) {
      const bc = f => { const p = E.filter(e => e.to === f).map(e => cols[layer[e.from]].indexOf(e.from)); return p.length ? p.reduce((s, v) => s + v, 0) / p.length : 0; };
      cols[k].sort((a, b) => bc(a) - bc(b) || first(a) - first(b));
    }
    /* components in no traced flow get no box: the page lists them on one quiet line under the graph */
    const iso = GM.comps.map(c => c.id).filter(f => !inG(f));
    const N = {};
    const tagW = tw("ENTRY POINT", 9.5) * 1.3 + 14;
    for (const f of files) {
      const c = info[f], name = compName(c), role = c.role || "";
      const ins = E.filter(e => e.to === f).length, entry = !!c.entry;
      const lines = roleLines(role);
      N[f] = { id: f, name, role, lines, entry, ins, module: c.module, files: c.files || [], title: c.title || "",
        w: Math.max(tw(name, 13, "mono") + (entry ? tagW + 10 : 0), ...lines.map(l => tw(l, 12))) + 28,
        h: Math.max(lines.length > 1 ? 68 : 54, PORT * Math.max(0, ins - 1) + 40) };
    }
    const big = cols.reduce((b, c, k) => (c.length > cols[b].length ? k : b), 0);
    const colW = cols.map(c => Math.max(...c.map(f => N[f].w)));
    const startW = Math.max(0, ...GM.starts.map(s => tw(s.label, 11.5, "mono") + 42));
    const cntW = tw("99 calls", 11) + 4;
    const gapNeed = k => { const src = cols[k].filter(f => E.some(e => e.from === f)); return 26 + 22 * Math.max(0, src.length - 1) + 16 + cntW + 24; };
    const natural = startW + 12 + colW.reduce((s, v) => s + v, 0) + cols.slice(0, -1).reduce((s, _, k) => s + Math.max(MINGAP, gapNeed(k)), 0) + 20;
    const extra = Math.max(0, width - natural), grow = nL > 1 ? Math.min(extra, 120 * (nL - 1)) / (nL - 1) : 0, pad = (extra - grow * (nL - 1)) / 2;
    let x = pad + startW + 12;
    const colX = [];
    cols.forEach((c, k) => { colX.push(x); c.forEach(f => { N[f].w = colW[k]; N[f].x = x; }); x += colW[k] + (k < nL - 1 ? Math.max(MINGAP, gapNeed(k)) + grow : 0); });
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
    const bottom = Math.max(...files.map(f => N[f].y + N[f].h));
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
    const st0 = GM.starts.filter((s, i, a) => a.findIndex(t => t.comp === s.comp) === i);
    /* every start label sits left of the first column, so one whose box is further right never runs under a box */
    const sx = Math.min(...st0.map(s => Math.min(N[s.comp].x, colX[0]) - tw(s.label, 11.5, "mono") - 34));
    const starts = st0.map(s => ({ ...s, x1: sx, y: Math.round(N[s.comp].y + N[s.comp].h / 2) }));
    const W = Math.round(Math.max(natural, width)), keyY = bottom + 34;
    const keys = [{ k: "start", t: "where a traced flow starts" }];
    [...new Set(E.map(e => e.calls.length))].sort((a, b) => a - b).forEach(c => keys.push({ k: "w", c, t: `${c} call${c > 1 ? "s" : ""}` }));
    return { dir: "lr", W, H: keyY + 20, N, files, iso, edges, buses, starts, keyY, keys, natural: Math.round(natural), flows: GM.flows };
  }
  /* left to right while it fits at TB_WHEN or more of its natural size; past that, top to bottom if that is narrower */
  const TB_WHEN = 0.8;
  /* ----------------------------------------------------------------------- (C') module graph, top to bottom */
  /* T7.16: a graph too wide for left to right (nanochat: 10 boxes, 17 arrows, 1750px, shown at 57%) is laid out in
     rows instead, one row per layer (a long layer splits into rows of at most TB.ROW boxes), so it fits the column.
     A layered (Sugiyama-style) drawing with orthogonal lines:
     - a line that skips rows runs down through a free slot of its own in each row between ("virtual" slots, ordered
       with the boxes to keep crossings down), so it never crosses a box;
     - each component's lines form one tree: a stub down from its box to a horizontal track in the gap below, the
       track to the slots and ports it serves, and on down; one track per tree per gap, tracks ordered to cross
       the fewest other trees' lines (every order tried for up to 7 tracks);
     - each arrow ends on its own port on its target's top, ports ordered by where their lines come from and
       TB.PX apart, so its "N calls" label sits just left of its own line, nearer to it than to any other line by
       more than a label height (a label zone under the lowest track keeps the tracks off the labels);
     - a flow start enters its box from the left, in a slot of its own beside the box.
     Crossings left (lines of two different components that meet) are counted in `crossings`. */
  const TB = { ROW: 3, SEP: 48, VBOX: 36, VSEP: 22, PX: 76, TRK: 16, GTOP: 14, M: 24, GAP0: 18, FREE: 44 };
  function layoutGraphTB(GM, width) {
    const E = GM.edges, info = Object.fromEntries(GM.comps.map(c => [c.id, c]));
    const inG = f => E.some(e => e.from === f || e.to === f) || GM.starts.some(s => s.comp === f);
    const order = [...GM.starts.map(s => s.comp), ...E.flatMap(e => [e.from, e.to])], first = f => order.indexOf(f);
    const files = GM.comps.map(c => c.id).filter(inG), iso = GM.comps.map(c => c.id).filter(f => !inG(f));
    const startOf0 = f => (GM.starts.some(s => s.comp === f) ? 0 : 1);
    /* 1. layers: the longest path from a source; a cycle is broken where a depth-first walk from the flows' starts
       (then the rest, in order of first use) comes back to a component on its own path, so the starts stay on top;
       long layers split */
    const back = new Set(), seen = new Set(), onPath = new Set();
    const walk = f => {
      seen.add(f); onPath.add(f);
      for (const e of E.filter(x => x.from === f)) {
        if (onPath.has(e.to)) back.add(e);
        else if (!seen.has(e.to)) walk(e.to);
      }
      onPath.delete(f);
    };
    [...files].sort((a, b) => (startOf0(a) - startOf0(b)) || first(a) - first(b)).forEach(f => { if (!seen.has(f)) walk(f); });
    const layer = {};
    const lay = f => {
      if (layer[f] === undefined) {
        const p = E.filter(e => e.to === f && !back.has(e)).map(e => e.from);
        layer[f] = -1;   /* guards a cycle the walk missed */
        layer[f] = p.length ? 1 + Math.max(...p.map(x => (layer[x] === -1 ? -1 : lay(x)))) : 0;
      }
      return layer[f];
    };
    files.forEach(lay);
    const nL = Math.max(...files.map(f => layer[f])) + 1, rows = [];
    for (let k = 0; k < nL; k++) {
      const fs = files.filter(f => layer[f] === k).sort((a, b) => first(a) - first(b));
      const parts = Math.ceil(fs.length / TB.ROW), per = Math.ceil(fs.length / parts);
      for (let i = 0; i < fs.length; i += per) rows.push(fs.slice(i, i + per));
    }
    const rowOf = {};
    rows.forEach((r, i) => r.forEach(f => (rowOf[f] = i)));
    const nR = rows.length;
    /* 2. boxes: as left to right, but ports go across the top, so a box is wide enough for its ports */
    const st0 = GM.starts.filter((s, i, a) => a.findIndex(t => t.comp === s.comp) === i);
    const startOf = Object.fromEntries(st0.map(s => [s.comp, s]));
    const tagW = tw("ENTRY POINT", 9.5) * 1.3 + 14, N = {};
    for (const f of files) {
      const c = info[f], name = compName(c), role = c.role || "", lines = roleLines(role), entry = !!c.entry;
      const ins = E.filter(e => e.to === f).length, st = startOf[f];
      N[f] = { id: f, name, role, lines, entry, ins, module: c.module, files: c.files || [], title: c.title || "",
        w: Math.round(Math.max(Math.max(tw(name, 13, "mono") + (entry ? tagW + 10 : 0), ...lines.map(l => tw(l, 12))) + 28,
          ins * TB.PX + 8)),
        h: lines.length > 1 ? 68 : 54, lead: st ? Math.round(tw(st.label, 11.5, "mono") + 34) : 0 };
    }
    /* 3. the trees: per source, a downward chain of virtual slots through every row its longer lines skip, and an
       upward one for lines to a row at or above its own (a cycle) */
    const trees = {};
    const tree = (s, dir) => (trees[s + dir] ??= { id: s + dir, src: s, dir, v: {}, edges: [] });
    for (const e of E) {
      const rs = rowOf[e.from], rt = rowOf[e.to], t = tree(e.from, rt > rs ? "d" : "u");
      t.edges.push(e);
      if (rt > rs) for (let j = rs + 1; j < rt; j++) t.v[j] = true;
      else for (let j = rt; j <= rs; j++) t.v[j] = true;
    }
    const T = Object.values(trees);
    /* row items: boxes and virtual slots */
    const items = rows.map(r => r.map(f => ({ k: "box", id: f })));
    for (const t of T) for (const j of Object.keys(t.v)) items[j].push({ k: "v", id: t.id, r: +j });
    const vkey = (tid, j) => `v:${tid}@${j}`;   /* one slot per tree per row */
    const key = it => (it.k === "box" ? it.id : vkey(it.id, it.r));
    /* the links between neighbouring rows, for ordering: (upper item, lower item) */
    const links = [];
    for (const t of T) {
      const rs = rowOf[t.src], vs = Object.keys(t.v).map(Number).sort((a, b) => a - b);
      if (t.dir === "d") {
        let prev = t.src, pr = rs;
        for (const j of vs) { links.push([pr, prev, vkey(t.id, j)]); prev = vkey(t.id, j); pr = j; }
        for (const e of t.edges) {
          const rt = rowOf[e.to];
          links.push([rt - 1, rt - 1 === rs ? t.src : vkey(t.id, rt - 1), e.to]);
        }
      } else {
        for (const j of vs) if (t.v[j + 1]) links.push([j, vkey(t.id, j), vkey(t.id, j + 1)]);
      }
    }
    const pos = () => { const p = {}; items.forEach(r => r.forEach((it, i) => (p[key(it)] = i))); return p; };
    const crossCount = () => {
      const p = pos();
      let n = 0;
      for (let r = 0; r < nR - 1; r++) {
        const L = links.filter(l => l[0] === r);
        for (let a = 0; a < L.length; a++) for (let b = a + 1; b < L.length; b++) {
          const u = p[L[a][1]] - p[L[b][1]], v = p[L[a][2]] - p[L[b][2]];
          if (u * v < 0) n++;
        }
      }
      return n;
    };
    const sortRow = (r, nb) => {
      const p = pos();
      const bc = it => { const xs = nb(key(it)).map(k => p[k]).filter(x => x !== undefined); return xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : p[key(it)]; };
      const m = new Map(items[r].map(it => [key(it), bc(it)]));
      items[r].sort((a, b) => m.get(key(a)) - m.get(key(b)) || p[key(a)] - p[key(b)]);
    };
    const ups = k => links.filter(l => l[2] === k).map(l => l[1]), downs = k => links.filter(l => l[1] === k).map(l => l[2]);
    let best = items.map(r => [...r]), bestN = crossCount();
    const cands = [best];
    for (let it = 0; it < 6; it++) {
      for (let r = 1; r < nR; r++) sortRow(r, ups);
      for (let r = nR - 2; r >= 0; r--) sortRow(r, downs);
      const n = crossCount();
      cands.push(items.map(r => [...r]));
      if (n < bestN) { bestN = n; best = items.map(r => [...r]); }
    }
    items.splice(0, items.length, ...best);
    /* steps 4-6 for the current row orders; the order kept is the one whose drawing crosses least (below) */
    let W0, X, port, gaps, crossings;
    const centre = k => (k.startsWith("v:") ? X[k] : X[k] + N[k].w / 2);
    const place = () => {
      /* 4. x: rows packed with their separations, each item pulled toward the items above it that feed it */
      const ext = it => (it.k === "box" ? [N[it.id].lead, N[it.id].w] : [0, 0]);   /* [left of x, right of x] */
      const sep = (a, b) => (a.k === "v" && b.k === "v" ? TB.VSEP : a.k === "v" || b.k === "v" ? TB.VBOX : TB.SEP);
      const packed = r => items[r].reduce((s, it, i) => s + ext(it)[0] + ext(it)[1] + (i ? sep(items[r][i - 1], it) : 0), 0);
      const inner = Math.max(...items.map((_, r) => packed(r)));
      W0 = Math.round(inner + 2 * TB.M);
      X = {};   /* an item's x: a box's left edge, a slot's line */
      for (let r = 0; r < nR; r++) {
        const row = items[r];
        let x = TB.M + (inner - packed(r)) / 2;
        const base = row.map((it, i) => { x += (i ? sep(row[i - 1], it) : 0) + ext(it)[0]; const v = x; x += ext(it)[1]; return v; });
        const want = row.map((it, i) => {
          const u = ups(key(it)).filter(k => X[k] !== undefined);
          if (!u.length) return base[i];
          const c = u.reduce((s, k) => s + centre(k), 0) / u.length;
          return it.k === "box" ? c - N[it.id].w / 2 : c;
        });
        /* left to right, never closer than the separation; then back from the right edge; then the left edge again */
        const at = [];
        row.forEach((it, i) => { at[i] = i ? Math.max(want[i], at[i - 1] + ext(row[i - 1])[1] + sep(row[i - 1], it) + ext(it)[0]) : Math.max(want[i], TB.M + ext(it)[0]); });
        for (let i = row.length - 1; i >= 0; i--) {
          const lim = i === row.length - 1 ? W0 - TB.M - ext(row[i])[1] : at[i + 1] - ext(row[i + 1])[0] - sep(row[i], row[i + 1]) - ext(row[i])[1];
          at[i] = Math.min(at[i], lim);
        }
        row.forEach((it, i) => { X[key(it)] = Math.round(at[i]); });
      }
      /* 5. ports: each target's incoming lines, ordered by the x they come down from, TB.PX apart across its top */
      const fromX = e => { const rs = rowOf[e.from], rt = rowOf[e.to]; return rt === rs + 1 ? centre(e.from) : rt > rs ? X[vkey(e.from + "d", rt - 1)] : X[vkey(e.from + "u", rt)]; };
      port = {};
      for (const f of files) {
        const ins = E.filter(e => e.to === f).sort((a, b) => fromX(a) - fromX(b) || first(a.from) - first(b.from));
        ins.forEach((e, k) => (port[e.from + ">" + e.to] = Math.round(X[f] + N[f].w / 2 + (k - (ins.length - 1) / 2) * TB.PX)));
      }
      /* 6. tracks: per tree per gap (gap g is above row g), the x range it spans, the lines above it (ending on it)
         and below it (leaving it) */
      gaps = [...Array(nR + 1)].map(() => []);
      for (const t of T) {
        const rs = rowOf[t.src], vx = j => X[vkey(t.id, j)];
        if (t.dir === "d") {
          const deepest = Math.max(...t.edges.map(e => rowOf[e.to]));
          for (let g = rs + 1; g <= deepest; g++) {
            const up = [g === rs + 1 ? centre(t.src) : vx(g - 1)];
            const down = t.edges.filter(e => rowOf[e.to] === g).map(e => port[e.from + ">" + e.to]);
            if (t.v[g]) down.push(vx(g));
            gaps[g].push({ t: t.id, src: t.src, up, down, ports: t.edges.filter(e => rowOf[e.to] === g) });
          }
        } else {
          const top = Math.min(...t.edges.map(e => rowOf[e.to]));
          gaps[rs + 1].push({ t: t.id, src: t.src, up: [centre(t.src), vx(rs)], down: [], ports: [] });
          for (let g = rs; g >= top; g--) {
            const down = [vx(g), ...t.edges.filter(e => rowOf[e.to] === g).map(e => port[e.from + ">" + e.to])];
            gaps[g].push({ t: t.id, src: t.src, up: g > top ? [vx(g - 1)] : [], down, ports: t.edges.filter(e => rowOf[e.to] === g) });
          }
        }
      }
      for (const G of gaps) for (const k of G) { const xs = [...k.up, ...k.down]; k.x0 = Math.min(...xs); k.x1 = Math.max(...xs); }
      /* the order of a gap's tracks: the fewest crossings with other trees' lines (a line above a track meets every
         track above its own end that spans its x; a line below, every track below its start) */
      const meets = (a, b) => {   /* a above b */
        if (a.src === b.src) return 0;
        const inR = (x, k) => x >= k.x0 - 0.5 && x <= k.x1 + 0.5;
        return a.down.filter(x => inR(x, b)).length + b.up.filter(x => inR(x, a)).length
          + a.down.filter(x => b.up.some(y => Math.abs(x - y) < 1)).length;   /* two lines on one x, overlapping */
      };
      const cost = ord => { let n = 0; for (let i = 0; i < ord.length; i++) for (let j = i + 1; j < ord.length; j++) n += meets(ord[i], ord[j]); return n; };
      const perms = a => (a.length <= 1 ? [a] : a.flatMap((x, i) => perms([...a.slice(0, i), ...a.slice(i + 1)]).map(p => [x, ...p])));
      crossings = 0;
      gaps.forEach((G, g) => {
        let ord;
        if (G.length <= 6) { ord = G; let c = cost(G); for (const p of perms(G)) { const pc = cost(p); if (pc < c) { c = pc; ord = p; } } }
        else { ord = []; for (const k of [...G].sort((a, b) => a.x0 - b.x0)) { let bi = 0, bc = Infinity; for (let i = 0; i <= ord.length; i++) { const c = cost([...ord.slice(0, i), k, ...ord.slice(i)]); if (c < bc) { bc = c; bi = i; } } ord.splice(bi, 0, k); } }
        gaps[g] = ord;
        crossings += cost(ord);
      });
      return crossings;
    };
    /* the orders the sweeps found, then neighbours swapped while that removes crossings from the drawing itself */
    let bestC = Infinity, bestItems = null;
    const tryOrder = () => { const c = place(); if (c < bestC) { bestC = c; bestItems = items.map(r => [...r]); } return c; };
    for (const cand of cands) { items.splice(0, items.length, ...cand.map(r => [...r])); tryOrder(); }
    for (let pass = 0; pass < 3 && bestC > 0; pass++) {
      let better = false;
      for (let r = 0; r < nR; r++) for (let i = 0; i + 1 < bestItems[r].length; i++) {
        items.splice(0, items.length, ...bestItems.map(x => [...x]));
        [items[r][i], items[r][i + 1]] = [items[r][i + 1], items[r][i]];
        const before = bestC;
        tryOrder();
        if (bestC < before) better = true;
      }
      /* two trees' slots swapped in every row they share (one row alone would only add a jog) */
      for (let a = 0; a < T.length; a++) for (let b = a + 1; b < T.length; b++) {
        items.splice(0, items.length, ...bestItems.map(x => [...x]));
        let shared = 0;
        for (const row of items) {
          const i = row.findIndex(it => it.k === "v" && it.id === T[a].id), j = row.findIndex(it => it.k === "v" && it.id === T[b].id);
          if (i >= 0 && j >= 0) { [row[i], row[j]] = [row[j], row[i]]; shared++; }
        }
        if (!shared) continue;
        const before = bestC;
        tryOrder();
        if (bestC < before) better = true;
      }
      if (!better) break;
    }
    items.splice(0, items.length, ...bestItems);
    place();
    /* 7. y: gap, row, gap, row ...; a gap holds its tracks, then the label zone over the ports below it */
    const wMax = Math.max(1.5, ...E.map(e => 1.5 * e.calls.length));
    const LZ = Math.max(56, 47 + wMax);
    const rowY = [], rowH = rows.map(r => Math.max(...r.map(f => N[f].h))), trackY = {};
    let y = 0;
    for (let g = 0; g <= nR; g++) {
      const G = gaps[g], ports = G.some(k => k.down.length);
      const top = y + (g === 0 ? TB.GAP0 : 0);
      G.forEach((k, i) => (trackY[g + "|" + k.t] = top + TB.GTOP + i * TB.TRK));
      const need = G.length ? TB.GTOP + (G.length - 1) * TB.TRK + (ports ? LZ : TB.GTOP) : g === 0 ? 0 : g === nR ? 0 : TB.FREE;
      y = top + need;
      if (g < nR) { rowY.push(Math.round(y)); y += rowH[g]; }
    }
    files.forEach(f => { N[f].x = X[f]; N[f].y = rowY[rowOf[f]]; });
    const bottom = y;
    /* 8. geometry: per tree, its tracks, the stub from its box, its slot lines; per edge, the drop into its port */
    const paths = [], edges = [], starts = [];
    for (const t of T) {
      const segs = [];
      const rs = rowOf[t.src], ty = g => trackY[g + "|" + t.id];
      gaps.forEach((G, g) => { const k = G.find(k => k.t === t.id); if (k && k.x1 > k.x0) segs.push(`M${k.x0 - 0.75} ${ty(g)}H${k.x1 + 0.75}`); });
      const sx = Math.round(centre(t.src)), first = t.dir === "d" ? ty(rs + 1) : ty(rs + 1);
      segs.push(`M${sx} ${N[t.src].y + N[t.src].h}V${first}`);
      const vs = Object.keys(t.v).map(Number).sort((a, b) => a - b);
      for (const j of vs) segs.push(t.dir === "d" ? `M${X[vkey(t.id, j)]} ${ty(j)}V${ty(j + 1)}` : `M${X[vkey(t.id, j)]} ${ty(j + 1)}V${ty(j)}`);
      paths.push({ from: t.src, d: segs.join("") });
      for (const e of t.edges) {
        const c = e.calls.length, w = 1.5 * c, px = port[e.from + ">" + e.to], yt = N[e.to].y, label = `${c} call${c > 1 ? "s" : ""}`;
        edges.push({ ...e, px, py0: ty(rowOf[e.to]), ye: yt - 2, w, label, lx: r1(px - 3 - w / 2), ly: r1(yt - 2 - 9 - w - 6) });
      }
    }
    for (const s of st0) {
      const b = N[s.comp], yy = Math.round(b.y + b.h / 2);
      starts.push({ ...s, x1: b.x - b.lead + 6, y: yy });
    }
    const keyY = bottom + 34;
    const keys = [{ k: "start", t: "where a traced flow starts" }];
    [...new Set(E.map(e => e.calls.length))].sort((a, b) => a - b).forEach(c => keys.push({ k: "w", c, t: `${c} call${c > 1 ? "s" : ""}` }));
    const W = Math.round(Math.max(W0, width));
    if (W > W0) {   /* centre the drawing in the extra room */
      const dx = Math.round((W - W0) / 2);
      files.forEach(f => (N[f].x += dx));
      for (const p of paths) p.d = p.d.replace(/([MH])(-?[\d.]+)/g, (m, op, v) => op + r1(+v + dx));
      for (const e of edges) { e.px += dx; e.lx = r1(e.lx + dx); }
      for (const s of starts) s.x1 += dx;
    }
    return { dir: "tb", W, H: keyY + 20, N, files, iso, edges, paths, starts, keyY, keys, natural: W0, flows: GM.flows,
      rows: rows.map(r => r.length), order: items.map(r => r.map(it => [key(it), X[key(it)]])), crossings };
  }
  function layoutGraph(GM, width) {
    const lr = layoutGraphLR(GM, width);
    if (width / lr.natural >= TB_WHEN) return lr;
    const tb = layoutGraphTB(GM, width);
    return tb.natural < lr.natural ? tb : lr;
  }
  function renderGraph(G) {
    let s = "";
    const nm = id => G.N[id].name;
    if (G.dir === "tb") s += edgesTB(G, nm);
    else s += edgesLR(G, nm);
    s += nodesAndKey(G);
    return `<svg class="dg dg-graph${G.dir === "tb" ? " dg-tb" : ""}" data-key="graph" data-dir="${G.dir}" data-natural="${G.natural}"${G.dir === "tb" ? ` data-crossings="${G.crossings}"` : ""} viewBox="0 0 ${G.W} ${G.H}" width="${G.W}" height="${G.H}" role="group" aria-label="Module graph: ${G.files.length} components and the calls between them">${s}</svg>`;
  }
  const edgeTip = (G, e, nm) => {
    const who = id => G.N[id].role ? `${esc(nm(id))} (${esc(G.N[id].role)})` : esc(nm(id));
    return `<b>${who(e.from)} calls ${who(e.to)}</b> · ${e.label} in the traced flows<br>` + e.calls.map(x => `<code>${esc(x.fn)}</code> · hop ${x.hop + 1}, ${esc(x.title)}`).join("<br>") + `<br>Click to see ${e.calls.length > 1 ? "them" : "it"} in the flow diagram`;
  };
  function edgesTB(G, nm) {
    let s = "";
    for (const p of G.paths) s += `<path class="gw gbus" data-from="${esc(p.from)}" stroke-width="1.5" d="${p.d}"/>`;
    for (const e of G.edges) {
      const w = e.w, lw = tw(e.label, 11);
      s += `<g class="dg-e" data-from="${esc(e.from)}" data-to="${esc(e.to)}" data-n="${e.calls.length}" data-tip="${esc(edgeTip(G, e, nm))}" tabindex="0" role="button" aria-label="${esc(nm(e.from))} calls ${esc(nm(e.to))}: ${e.label}">`
        + `<path class="hitl" d="M${e.px} ${e.py0}V${e.ye}"/><rect class="hit" x="${r1(e.lx - lw - 4)}" y="${r1(e.ly - 12)}" width="${r1(lw + 8)}" height="16"/>`
        + `<path class="gw gdrop" stroke-width="${w}" d="M${e.px} ${e.py0 - 0.75}V${r1(e.ye - 9 - w)}"/><path class="gh" d="M${e.px} ${e.ye}L${r1(e.px - 3.5 - w)} ${r1(e.ye - 9 - w)}L${r1(e.px + 3.5 + w)} ${r1(e.ye - 9 - w)}Z"/>`
        + `<text class="gcnt halo" x="${e.lx}" y="${e.ly}" text-anchor="end">${e.label}</text></g>`;
    }
    for (const st of G.starts) {
      const xe = G.N[st.comp].x - 2;
      s += `<g class="gst"><circle class="start" cx="${r1(st.x1)}" cy="${st.y}" r="4.5"/><path class="gw" stroke-width="1.5" d="M${r1(st.x1)} ${st.y}H${xe - 9}"/><path class="gh" d="M${xe} ${st.y}L${xe - 9} ${st.y - 4.2}L${xe - 9} ${st.y + 4.2}Z"/>${st.label ? `<text class="gstart halo" x="${r1(st.x1 + 10)}" y="${st.y - 8}">${esc(st.label)}</text>` : ""}</g>`;
    }
    return s;
  }
  function edgesLR(G, nm) {
    let s = "";
    for (const b of G.buses) s += `<path class="gw gbus" data-from="${esc(b.from)}" stroke-width="1.5" d="M${b.x0} ${b.sy}H${b.bx}${b.y0 < b.y1 ? `M${b.bx} ${b.y0 - 0.75}V${b.y1 + 0.75}` : ""}"/>`;
    for (const e of G.edges) {
      const c = e.calls.length, w = e.w, xe = e.xe;
      const tip = edgeTip(G, e, nm);
      s += `<g class="dg-e" data-from="${esc(e.from)}" data-to="${esc(e.to)}" data-n="${c}" data-tip="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(nm(e.from))} calls ${esc(nm(e.to))}: ${e.label}">`
        + `<path class="hitl" d="M${e.bx} ${e.py}H${xe}"/><rect class="hit" x="${r1(e.lx - tw(e.label, 11) - 4)}" y="${r1(e.ly - 12)}" width="${r1(tw(e.label, 11) + 8)}" height="16"/>`
        + `<path class="gw gdrop" stroke-width="${w}" d="M${e.bx - 0.75} ${e.py}H${r1(xe - 9 - w)}"/><path class="gh" d="M${xe} ${e.py}L${r1(xe - 9 - w)} ${r1(e.py - 3.5 - w)}L${r1(xe - 9 - w)} ${r1(e.py + 3.5 + w)}Z"/>`
        + `<text class="gcnt halo" x="${r1(e.lx)}" y="${e.ly}" text-anchor="end">${e.label}</text></g>`;
    }
    for (const st of G.starts) {
      const xe = G.N[st.comp].x - 2;
      s += `<g class="gst"><circle class="start" cx="${r1(st.x1)}" cy="${st.y}" r="4.5"/><path class="gw" stroke-width="1.5" d="M${r1(st.x1)} ${st.y}H${xe - 9}"/><path class="gh" d="M${xe} ${st.y}L${xe - 9} ${st.y - 4.2}L${xe - 9} ${st.y + 4.2}Z"/>${st.label ? `<text class="gstart halo" x="${r1(st.x1 + 10)}" y="${st.y - 8}">${esc(st.label)}</text>` : ""}</g>`;
    }
    return s;
  }
  function nodesAndKey(G) {
    let s = "";
    for (const f of G.files) {
      const b = G.N[f], name = b.name, ny = b.lines.length > 1 ? -10 : b.lines.length ? -3 : 5;   /* name baseline, from the box's middle */
      const head = b.title ? esc(b.title).replace(/`([^`\n]+)`/g, "<code>$1</code>") : `<code>${esc(name)}</code>${b.role ? " · " + esc(b.role) : ""}`;
      const tip = `<b>${head}</b>${b.entry ? "<br>Holds the entry point" : ""}${b.files.length > 1 || b.title ? `<br>Files: ${b.files.map(x => `<code>${esc(x)}</code>`).join(", ")}` : ""}<br>${b.module ? "Click for its module" : "No module section for this file"}`;
      s += `<g class="dg-node" data-comp="${esc(f)}" data-files="${esc(b.files.join(" "))}" data-tip="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(name)}${b.role ? ": " + esc(b.role) : ""}${b.files.length > 1 ? ` (files: ${esc(b.files.join(", "))})` : ""}"><rect class="gbox" x="${r1(b.x)}" y="${r1(b.y)}" width="${r1(b.w)}" height="${b.h}" rx="8"/>`
        + `<text class="gname" x="${r1(b.x + 14)}" y="${r1(b.y + b.h / 2 + ny)}">${esc(name)}</text>`
        + b.lines.map((l, k) => `<text class="grole" x="${r1(b.x + 14)}" y="${r1(b.y + b.h / 2 + ny + 17 + 14 * k)}">${esc(l)}</text>`).join("")
        + (b.entry ? `<rect class="gtagbox" x="${r1(b.x + 14 + tw(name, 13, "mono") + 10)}" y="${r1(b.y + b.h / 2 + ny - 12)}" width="${r1(tw("ENTRY POINT", 9.5) * 1.3 + 12)}" height="16" rx="4"/><text class="gtag" x="${r1(b.x + 14 + tw(name, 13, "mono") + 16)}" y="${r1(b.y + b.h / 2 + ny - 1)}">ENTRY POINT</text>` : "") + `</g>`;
    }
    let x = D.gut - 12;
    const y = G.keyY;
    s += `<g class="dg-key"><line class="sep" x1="${D.gut - 16}" y1="${y - 20}" x2="${G.W - D.gut + 16}" y2="${y - 20}"/>`;
    for (const k of G.keys) {
      if (k.k === "start") { s += `<circle class="start" cx="${x + 5}" cy="${y}" r="4.5"/><text class="lgt" x="${x + 16}" y="${y + 4}">${k.t}</text>`; x += 16 + tw(k.t, 11.5) + 26; }
      else { s += `<path class="gw" stroke-width="${1.5 * k.c}" d="M${x} ${y}H${x + 28}"/><text class="lgt" x="${x + 36}" y="${y + 4}">${k.t}</text>`; x += 36 + tw(k.t, 11.5) + 22; }
    }
    s += `<text class="lgt" x="${r1(x)}" y="${y + 4}">between components, counted across the ${G.flows} traced flow${G.flows === 1 ? "" : "s"}</text></g>`;
    return s;
  }

  return { tw, wrapText, edgeOf, lanesOf, layoutSeq, renderSeq, resolver, graphModel, compName, layoutGraph, layoutGraphLR,
    layoutGraphTB, renderGraph, D, PORT, TB, TB_WHEN };
})();
