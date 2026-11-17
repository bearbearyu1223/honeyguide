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
  /* where a hop's data goes: on a self-call, or when the callee makes the next hop, it stays in the callee's lane as a
     pill ("data"); otherwise it returns to the hop's own caller ("ret"), never to a lane that merely acts next (review
     r2: a nested call, engine -> tokenizer, followed by a call from the root lane drew its return to the root lane) */
  function edgeOf(P, i) {
    const h = P[i];
    if (!h.edge) return null;
    const nx = P[i + 1], src = h.to;
    return h.from === src || (nx && nx.from === src) ? { kind: "data", lane: src } : { kind: "ret", from: src, to: h.from };
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
     path is listed on hover and in the expanded node */
  const base = f => (f.endsWith("/") ? f : f.split("/").pop());
  const compName = c => c.name || base((c.files || [])[0] || c.id) + ((c.files || []).length > 1 ? ` +${c.files.length - 1}` : "");

  /* ------------------------------------------------------------------- (C) the component map (T7.17, UX v4) */
  /* The T7.16 module graph was hard to read and to navigate. The component map:
     - three bands derived from the graph, top to bottom: ENTRY POINTS (no traced call reaches them), STAGES (called
       and calling; one row per longest-path step) and LEAVES (call nothing traced); captions in a left gutter, so
       no line ever runs under a caption;
     - every edge its own route: its own port on the caller's bottom and on the callee's top, a smooth curve between
       rows, and its own slot through any row it skips (no shared bus segments); a call back up runs in its own
       channel right of the boxes;
     - stroke weight encodes the call count; the count is on hover only (no label on every line);
     - "main paths" (every edge used by two or more flows, plus each component's most-used incoming edge) is the
       default view; the rest are drawn too, marked minor, and shown by "Show all N calls" (page.js), so toggling
       never moves a box;
     - row orders are chosen to cross least in the main view, then in the full view; both counts are reported;
     - all text is at least MAP.MIN px in the SVG's own units, so a fit at MAP.MIN_SCALE or more never shows text
       under 12 px. */
  const MAP = { M: 20, GUT: 128, SEP: 40, VSEP: 18, VBOX: 26, GAP: 64, BAND: 12, NAME: 14.5, TXT: 13, MIN: 13, ROLE: 196,
    PORT: 24, CH: 16, MAXROW: 5 };
  MAP.MIN_SCALE = 12 / MAP.MIN;
  const BANDS = { entry: ["Entry points", "No traced call reaches them: where the flows begin"],
    stage: ["Stages", "Called and calling, in the order the flows reach them"],
    leaf: ["Leaves", "Call nothing in the traced flows: the model, kernels, helpers"] };
  const flowsOf = e => new Set(e.calls.map(c => c.flow)).size;
  /* main paths: every edge two or more flows use, and each component's most-used way in (flows, then calls) */
  function mainEdges(E) {
    const main = new Set(E.filter(e => flowsOf(e) >= 2));
    const best = new Map();
    E.forEach((e, i) => {
      const b = best.get(e.to), k = [flowsOf(e), e.calls.length, -i];
      if (!b || k[0] > b.k[0] || (k[0] === b.k[0] && (k[1] > b.k[1] || (k[1] === b.k[1] && k[2] > b.k[2])))) best.set(e.to, { e, k });
    });
    for (const { e } of best.values()) main.add(e);
    return main;
  }
  const expLabel = (n, open) => (open ? "hide files" : `+${n - 1} file${n > 2 ? "s" : ""}`);
  function fileLine(f) { return f.length > 34 ? "…" + f.slice(-33) : f; }
  /* a cubic between two vertical tangents, as a polyline (for crossing counts and hit tests) */
  function cubicPts(x1, y1, x2, y2, n = 12) {
    const ym = (y1 + y2) / 2, out = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n, u = 1 - t;
      out.push([u * u * u * x1 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x2, u * u * u * y1 + 3 * u * u * t * ym + 3 * u * t * t * ym + t * t * t * y2]);
    }
    return out;
  }
  function segX(a, b, c, d) {   /* the point where segments ab and cd cross, or null (touching ends count) */
    const r = [b[0] - a[0], b[1] - a[1]], s = [d[0] - c[0], d[1] - c[1]], den = r[0] * s[1] - r[1] * s[0];
    if (Math.abs(den) < 1e-9) return null;
    const t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den, u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den;
    return t >= 0 && t <= 1 && u >= 0 && u <= 1 ? [a[0] + t * r[0], a[1] + t * r[1]] : null;
  }
  /* crossing points between edges' polylines, each point once */
  function crossingsOf(edges) {
    const pts = [];
    for (let i = 0; i < edges.length; i++) for (let j = i + 1; j < edges.length; j++) {
      const A = edges[i].pts, B = edges[j].pts;
      for (let a = 0; a + 1 < A.length; a++) for (let b = 0; b + 1 < B.length; b++) {
        const p = segX(A[a], A[a + 1], B[b], B[b + 1]);
        if (p && !pts.some(q => q.i === i && q.j === j && Math.hypot(q.p[0] - p[0], q.p[1] - p[1]) < 3)) pts.push({ i, j, p });
      }
    }
    return pts;
  }
  function layoutMap(GM, width, opt = {}) {
    const expanded = opt.expanded || new Set();
    const E = GM.edges.filter(e => e.from !== e.to), info = Object.fromEntries(GM.comps.map(c => [c.id, c]));
    const inG = f => E.some(e => e.from === f || e.to === f) || GM.starts.some(s => s.comp === f);
    const order = [...GM.starts.map(s => s.comp), ...E.flatMap(e => [e.from, e.to])], first = f => order.indexOf(f);
    const files = GM.comps.map(c => c.id).filter(inG).sort((a, b) => first(a) - first(b));
    const iso = GM.comps.map(c => c.id).filter(f => !inG(f));
    const main = mainEdges(E);
    /* 1. kinds and layers */
    const kind = {};
    for (const f of files) {
      const i = E.filter(e => e.to === f).length, o = E.filter(e => e.from === f).length;
      kind[f] = i === 0 ? "entry" : o === 0 ? "leaf" : "stage";
    }
    if (files.length && !files.some(f => kind[f] === "entry")) {   /* everything is called: the flows' starts lead */
      const s = files.filter(f => GM.starts.some(x => x.comp === f));
      (s.length ? s : [files[0]]).forEach(f => (kind[f] = "entry"));
    }
    const back = new Set(), seen = new Set(), onPath = new Set();
    const walk = f => {
      seen.add(f); onPath.add(f);
      for (const e of E.filter(x => x.from === f)) {
        if (onPath.has(e.to) || kind[e.to] === "entry") back.add(e);
        else if (!seen.has(e.to)) walk(e.to);
      }
      onPath.delete(f);
    };
    files.filter(f => kind[f] === "entry").forEach(walk);
    files.forEach(f => { if (!seen.has(f)) walk(f); });
    const layer = {};
    const lay = f => {
      if (layer[f] !== undefined) return layer[f];
      if (kind[f] === "entry") return (layer[f] = 0);
      layer[f] = 1;   /* guards a cycle the walk missed */
      const p = E.filter(e => e.to === f && !back.has(e) && kind[e.from] !== "leaf").map(e => e.from);
      return (layer[f] = p.length ? 1 + Math.max(...p.map(lay)) : 1);
    };
    files.filter(f => kind[f] !== "leaf").forEach(lay);
    const lastStage = Math.max(0, ...files.filter(f => kind[f] !== "leaf").map(f => layer[f]));
    files.filter(f => kind[f] === "leaf").forEach(f => (layer[f] = lastStage + 1));
    /* 2. boxes */
    const st0 = GM.starts.filter((s, i, a) => a.findIndex(t => t.comp === s.comp) === i);
    const startOf = Object.fromEntries(st0.map(s => [s.comp, s]));
    const N = {};
    for (const f of files) {
      const c = info[f], fl = c.files || [], name = c.name && !/ \+\d+$/.test(c.name) ? c.name : base(fl[0] || c.id), role = c.role || "";
      let lines = role ? wrapText(role, MAP.ROLE, MAP.TXT) : [];
      if (lines.length > 2) { let l2 = lines.slice(1).join(" "); while (l2 && tw(l2 + "…", MAP.TXT) > MAP.ROLE) l2 = l2.slice(0, -1); lines = [lines[0], l2.trimEnd() + "…"]; }
      const open = expanded.has(f) && fl.length > 1;
      const flines = open ? fl.map(fileLine) : [];
      const tagW = c.entry ? tw("entry", 13) + 14 : 0;
      const expW = fl.length > 1 ? tw(expLabel(fl.length, open), MAP.MIN) + 24 : 0;
      const ins = E.filter(e => e.to === f && !back.has(e)).length, outs = E.filter(e => e.from === f && !back.has(e)).length;
      const w = Math.round(Math.max(150, tw(name, MAP.NAME, "mono") + (tagW ? tagW + 8 : 0) + (expW ? expW + 12 : 0) + 32, ...lines.map(l => tw(l, MAP.TXT) + 32),
        ...flines.map(l => tw(l, MAP.MIN, "mono") + 32), (Math.max(ins, outs) + 1) * MAP.PORT));
      const h = 22 + 20 + lines.length * 18 + (flines.length ? 8 + flines.length * 18 : 0) + 8;
      N[f] = { id: f, name, role, lines, kind: kind[f], entry: !!c.entry, module: c.module, files: fl, title: c.title || "", open, flines,
        w, h, lead: startOf[f] ? Math.round(tw(startOf[f].label, MAP.MIN, "mono") + 40) : 0 };
    }
    /* 3. rows: a layer per row, a long one split (at most what fits the width, 2 to MAXROW) */
    const nL = files.length ? Math.max(...files.map(f => layer[f])) + 1 : 0;
    /* a layer longer than the width splits into the fewest even rows that fit (at most MAXROW boxes a row) */
    const room = width - MAP.GUT - 2 * MAP.M;
    const packedW = fs => fs.reduce((s, f) => s + N[f].w + N[f].lead, 0) + MAP.SEP * (fs.length - 1);
    const rows = [], rowKind = [];
    for (let k = 0; k < nL; k++) {
      const fs = files.filter(f => layer[f] === k);
      if (!fs.length) continue;
      let parts = Math.ceil(fs.length / MAP.MAXROW), chunks;
      for (;; parts++) {
        const per = Math.ceil(fs.length / parts);
        chunks = [];
        for (let i = 0; i < fs.length; i += per) chunks.push(fs.slice(i, i + per));
        if (per === 1 || chunks.every(c => packedW(c) <= room)) break;
      }
      for (const c of chunks) { rows.push(c); rowKind.push(kind[fs[0]] === "entry" ? "entry" : kind[fs[0]] === "leaf" ? "leaf" : "stage"); }
    }
    const rowOf = {};
    rows.forEach((r, i) => r.forEach(f => (rowOf[f] = i)));
    const nR = rows.length;
    /* forward edges (down at least one row) are laid out; any other is a call back up, drawn in a side channel */
    const fwd = E.filter(e => !back.has(e) && rowOf[e.to] > rowOf[e.from]);
    const up = E.filter(e => !fwd.includes(e));
    const eid = e => E.indexOf(e);
    const vkey = (e, j) => `v:${eid(e)}@${j}`;
    const items = rows.map(r => r.map(f => ({ k: "box", id: f })));
    for (const e of fwd) for (let j = rowOf[e.from] + 1; j < rowOf[e.to]; j++) items[j].push({ k: "v", id: vkey(e, j), e });
    const key = it => it.id;
    const chain = e => [e.from, ...[...Array(Math.max(0, rowOf[e.to] - rowOf[e.from] - 1))].map((_, k) => vkey(e, rowOf[e.from] + 1 + k)), e.to];
    const links = [];   /* [upper row, upper key, lower key, edge] */
    for (const e of fwd) { const c = chain(e); for (let k = 0; k + 1 < c.length; k++) links.push([rowOf[e.from] + k, c[k], c[k + 1], e]); }
    const pos = () => { const p = {}; items.forEach(r => r.forEach((it, i) => (p[key(it)] = i))); return p; };
    const orderCross = () => {
      const p = pos();
      let n = 0;
      for (let r = 0; r < nR - 1; r++) {
        const L = links.filter(l => l[0] === r);
        for (let a = 0; a < L.length; a++) for (let b = a + 1; b < L.length; b++) {
          const w = main.has(L[a][3]) && main.has(L[b][3]) ? 100 : 1;   /* main crossings first */
          if ((p[L[a][1]] - p[L[b][1]]) * (p[L[a][2]] - p[L[b][2]]) < 0) n += w;
        }
      }
      return n;
    };
    const ups = k => links.filter(l => l[2] === k).map(l => l[1]), downs = k => links.filter(l => l[1] === k).map(l => l[2]);
    const sortRow = (r, nb) => {
      const p = pos();
      const bc = it => { const xs = nb(key(it)).map(k => p[k]).filter(x => x !== undefined); return xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : p[key(it)]; };
      const m = new Map(items[r].map(it => [key(it), bc(it)]));
      items[r].sort((a, b) => m.get(key(a)) - m.get(key(b)) || p[key(a)] - p[key(b)]);
    };
    const cands = [items.map(r => [...r])];
    for (let it = 0; it < 6; it++) {
      for (let r = 1; r < nR; r++) sortRow(r, ups);
      for (let r = nR - 2; r >= 0; r--) sortRow(r, downs);
      cands.push(items.map(r => [...r]));
    }
    /* 4. x, ports, y and routes for one row order */
    const rowH = rows.map(r => Math.max(...r.map(f => N[f].h)));
    const rowY = [];
    {
      let y = 16;
      rows.forEach((r, i) => {
        if (i === 0 || rowKind[i] !== rowKind[i - 1]) y += i ? MAP.BAND : 0;
        rowY.push(y);
        y += rowH[i] + MAP.GAP;
      });
    }
    let X, inner;
    const centre = k => (k.startsWith("v:") ? X[k] : X[k] + N[k].w / 2);
    const ext = it => (it.k === "box" ? [N[it.id].lead, N[it.id].w] : [0, 0]);
    const sep = (a, b) => (a.k === "v" && b.k === "v" ? MAP.VSEP : a.k === "v" || b.k === "v" ? MAP.VBOX : MAP.SEP);
    function placeX() {
      const packed = r => items[r].reduce((s, it, i) => s + ext(it)[0] + ext(it)[1] + (i ? sep(items[r][i - 1], it) : 0), 0);
      inner = Math.max(0, ...items.map((_, r) => packed(r)));
      const L0 = MAP.GUT + MAP.M, R0 = MAP.GUT + MAP.M + inner;
      X = {};
      const fit = (r, want) => {
        const row = items[r], at = [];
        row.forEach((it, i) => { at[i] = i ? Math.max(want[i], at[i - 1] + ext(row[i - 1])[1] + sep(row[i - 1], it) + ext(it)[0]) : Math.max(want[i], L0 + ext(it)[0]); });
        for (let i = row.length - 1; i >= 0; i--) {
          const lim = i === row.length - 1 ? R0 - ext(row[i])[1] : at[i + 1] - ext(row[i + 1])[0] - sep(row[i], row[i + 1]) - ext(row[i])[1];
          at[i] = Math.min(at[i], lim);
        }
        row.forEach((it, i) => { X[key(it)] = at[i]; });
      };
      for (let r = 0; r < nR; r++) {
        let x = L0 + (inner - packed(r)) / 2;
        fit(r, items[r].map((it, i) => { x += (i ? sep(items[r][i - 1], it) : 0) + ext(it)[0]; const v = x; x += ext(it)[1]; return v; }));
      }
      const pull = (r, nb) => {
        const want = items[r].map(it => {
          const u = nb(key(it)).filter(k => X[k] !== undefined);
          if (!u.length) return X[key(it)];
          const c = u.reduce((s, k) => s + centre(k), 0) / u.length;
          return it.k === "box" ? c - N[it.id].w / 2 : c;
        });
        fit(r, want);
      };
      for (let it = 0; it < 4; it++) {
        for (let r = 1; r < nR; r++) pull(r, ups);
        for (let r = nR - 2; r >= 0; r--) pull(r, downs);
      }
      for (let r = 1; r < nR; r++) pull(r, ups);
      for (const k in X) X[k] = Math.round(X[k]);
    }
    function route() {
      /* ports: a box's lines out along its bottom, ordered by where they go next; in along its top, by where they
         come from; MAP.PORT apart (less when the box is narrow), centred */
      const port = {};
      const spread = (f, list, side) => {
        const n = list.length, step = n > 1 ? Math.min(MAP.PORT, (N[f].w - 28) / (n - 1)) : 0;
        list.forEach((e, k) => (port[side + eid(e)] = Math.round(X[f] + N[f].w / 2 + (k - (n - 1) / 2) * step)));
      };
      for (const f of files) {
        const outs = fwd.filter(e => e.from === f).sort((a, b) => centre(chain(a)[1]) - centre(chain(b)[1]) || first(a.to) - first(b.to));
        const ins = fwd.filter(e => e.to === f).sort((a, b) => { const ca = chain(a), cb = chain(b); return centre(ca[ca.length - 2]) - centre(cb[cb.length - 2]) || first(a.from) - first(b.from); });
        spread(f, outs, "o"); spread(f, ins, "i");
      }
      const out = [];
      for (const e of fwd) {
        const c = chain(e), w = Math.min(6, 1.25 + 1.25 * (e.calls.length - 1)), ah = 8 + w;
        const r0 = rowOf[e.from], r1 = rowOf[e.to];
        let x = port["o" + eid(e)], y = rowY[r0] + N[e.from].h;
        let d = `M${x} ${y}`, pts = [[x, y]];
        for (let k = 1; k < c.length; k++) {
          const last = k === c.length - 1, j = r0 + k;
          const x2 = last ? port["i" + eid(e)] : X[c[k]], y2 = last ? rowY[j] - ah : rowY[j] - 4;
          const ym = (y + y2) / 2;
          d += `C${x} ${r1v(ym)} ${x2} ${r1v(ym)} ${x2} ${y2}`;
          pts = pts.concat(cubicPts(x, y, x2, y2).slice(1));
          x = x2; y = y2;
          if (!last) { const yb = rowY[j] + rowH[j] + 4; d += `V${yb}`; pts.push([x, yb]); y = yb; }
        }
        const yt = rowY[r1];
        out.push({ e, from: e.from, to: e.to, calls: e.calls, flows: flowsOf(e), main: main.has(e), w, d, pts,
          head: `M${x} ${yt}L${r1v(x - 4 - w / 2)} ${r1v(yt - ah)}L${r1v(x + 4 + w / 2)} ${r1v(yt - ah)}Z`, px: x });
      }
      /* calls back up: right of every box, one channel each, from the caller's right side to the callee's */
      const right = MAP.GUT + MAP.M + inner;
      up.forEach((e, k) => {
        const w = Math.min(6, 1.25 + 1.25 * (e.calls.length - 1)), cx = right + 20 + k * MAP.CH;
        /* each its own side ports: lines into (or out of) one box's side are 12 px apart */
        const outsK = up.filter(x => x.from === e.from), insK = up.filter(x => x.to === e.to);
        const sy = Math.round(rowY[rowOf[e.from]] + N[e.from].h / 2 + 6 + 12 * outsK.indexOf(e)), ty = Math.round(rowY[rowOf[e.to]] + N[e.to].h / 2 - 6 - 12 * insK.indexOf(e));
        const sx = X[e.from] + N[e.from].w, tx = X[e.to] + N[e.to].w + 2;
        out.push({ e, from: e.from, to: e.to, calls: e.calls, flows: flowsOf(e), main: main.has(e), w, back: true,
          d: `M${sx} ${sy}H${cx}V${ty}H${tx + 9 + w / 2}`, pts: [[sx, sy], [cx, sy], [cx, ty], [tx, ty]],
          head: `M${tx} ${ty}L${r1v(tx + 9 + w / 2)} ${r1v(ty - 4 - w / 2)}L${r1v(tx + 9 + w / 2)} ${r1v(ty + 4 + w / 2)}Z`, px: tx });
      });
      return out;
    }
    const r1v = v => Math.round(v * 10) / 10;
    const score = () => {
      placeX();
      const R = route(), m = crossingsOf(R.filter(x => x.main)).length, a = crossingsOf(R).length;
      const len = R.filter(x => x.main).reduce((s, x) => s + x.pts.reduce((t, p, i) => t + (i ? Math.abs(p[0] - x.pts[i - 1][0]) : 0), 0), 0);
      return [m, a, len, R];
    };
    let best = null, bestItems = null;
    const better = (s, b) => !b || s[0] < b[0] || (s[0] === b[0] && (s[1] < b[1] || (s[1] === b[1] && s[2] < b[2] - 1)));
    const tryIt = () => { const s = score(); if (better(s, best)) { best = s; bestItems = items.map(r => [...r]); } return s; };
    const seenOrd = new Set();
    for (const cand of cands) {
      const sig = JSON.stringify(cand.map(r => r.map(key)));
      if (seenOrd.has(sig)) continue;
      seenOrd.add(sig);
      items.splice(0, items.length, ...cand.map(r => [...r]));
      tryIt();
    }
    void orderCross;
    /* then neighbouring items swapped while that removes crossings from the drawing itself */
    for (let pass = 0; pass < 3 && best; pass++) {
      let gained = false;
      for (let r = 0; r < nR; r++) for (let i = 0; i + 1 < bestItems[r].length; i++) {
        items.splice(0, items.length, ...bestItems.map(x => [...x]));
        [items[r][i], items[r][i + 1]] = [items[r][i + 1], items[r][i]];
        const before = best;
        tryIt();
        if (best !== before) gained = true;
      }
      if (!gained) break;
    }
    if (bestItems) items.splice(0, items.length, ...bestItems);
    placeX();
    const edges = files.length ? route() : [];
    const crossMain = crossingsOf(edges.filter(x => x.main)), crossAll = crossingsOf(edges);
    files.forEach(f => { N[f].x = X[f]; N[f].y = rowY[rowOf[f]]; });
    const right = MAP.GUT + MAP.M + inner + (up.length ? 20 + up.length * MAP.CH + 8 : 0);
    const bottom = nR ? rowY[nR - 1] + rowH[nR - 1] : 16;
    /* bands: one per run of rows of one kind; the caption in the gutter beside its first row */
    const bands = [];
    rows.forEach((_, i) => {
      if (i && rowKind[i] === rowKind[i - 1]) { bands[bands.length - 1].r1 = i; return; }
      bands.push({ kind: rowKind[i], r0: i, r1: i });
    });
    for (const b of bands) {
      b.y = rowY[b.r0] - 14; b.h = rowY[b.r1] + rowH[b.r1] + 14 - b.y;
      b.label = BANDS[b.kind][0]; b.note = BANDS[b.kind][1]; b.n = rows.slice(b.r0, b.r1 + 1).flat().length;
    }
    const starts = st0.map(s => { const b = N[s.comp]; return { ...s, x1: b.x - b.lead + 6, y: Math.round(b.y + 21) }; });
    const W0 = Math.round(right + MAP.M), W = Math.round(Math.max(W0, opt.stretch ? width : W0));
    if (W > W0) {   /* centre the drawing (not the gutter) in the extra room */
      const dx = Math.round((W - W0) / 2);
      files.forEach(f => (N[f].x += dx));
      for (const e of edges) {
        e.d = e.d.replace(/([MCHL])([^MCVHLZ]*)/g, (m, op, args) => op + (op === "V" ? args : args.trim().split(/[\s,]+/).map((v, i) => (op === "H" || i % 2 === 0 ? r1v(+v + dx) : v)).join(" ")));
        e.head = e.head.replace(/([ML])(-?[\d.]+)/g, (m, op, v) => op + r1v(+v + dx));
        e.pts = e.pts.map(([x, y]) => [x + dx, y]); e.px += dx;
      }
      for (const s of starts) s.x1 += dx;
    }
    const keyY = bottom + 44;
    const nCalls = E.reduce((s, e) => s + e.calls.length, 0);
    return { dir: "map", W, H: keyY + 22, N, files, iso, edges, bands, starts, keyY, natural: W0, flows: GM.flows, rows: rows.map(r => r.length),
      order: items.map(r => r.map(key)), crossings: { main: crossMain.length, all: crossAll.length }, crossAt: { main: crossMain.map(c => c.p), all: crossAll.map(c => c.p) },
      nMain: edges.filter(e => e.main).length, nEdges: edges.length, nCalls, nMainCalls: edges.filter(e => e.main).reduce((s, e) => s + e.calls.length, 0) };
  }
  const edgeTip = (G, e) => {
    const who = id => G.N[id].role ? `<code>${esc(G.N[id].name)}</code> (${esc(G.N[id].role)})` : `<code>${esc(G.N[id].name)}</code>`;
    return `<b>${who(e.from)} calls ${who(e.to)}</b><br>${e.calls.length} call${e.calls.length > 1 ? "s" : ""} in ${e.flows} traced flow${e.flows > 1 ? "s" : ""}${e.main ? "" : " · not a main path"}<br>`
      + e.calls.map(x => `<code>${esc(x.fn)}</code> · hop ${x.hop + 1}, ${esc(x.title)}`).join("<br>") + `<br>Click to see ${e.calls.length > 1 ? "them" : "it"} in the flow diagram`;
  };
  function renderMap(G, view = "main") {
    let s = "";
    for (const b of G.bands) s += `<g class="band b-${b.kind}"><rect class="bandbg" x="8" y="${b.y}" width="${G.W - 16}" height="${b.h}" rx="14"/><g class="bandc" data-tip="${esc(`<b>${b.label}</b> · ${b.note}`)}"><text class="bandt" x="24" y="${b.y + 30}">${esc(b.label.toUpperCase())}</text><text class="bandn" x="24" y="${b.y + 50}">${b.n} component${b.n > 1 ? "s" : ""}</text></g></g>`;
    for (const e of G.edges) {
      const nm = `${esc(G.N[e.from].name)} calls ${esc(G.N[e.to].name)}: ${e.calls.length} call${e.calls.length > 1 ? "s" : ""}`;
      s += `<g class="dg-e${e.main ? "" : " minor"}${e.back ? " back" : ""}" data-from="${esc(e.from)}" data-to="${esc(e.to)}" data-n="${e.calls.length}" data-flows="${e.flows}" data-main="${e.main ? 1 : 0}" data-tip="${esc(edgeTip(G, e))}" tabindex="-1" role="button" aria-label="${nm}">`
        + `<path class="hitl" d="${e.d}"/><path class="gw" stroke-width="${e.w}" d="${e.d}"/><path class="gh" d="${e.head}"/></g>`;
    }
    for (const st of G.starts) {
      const xe = G.N[st.comp].x - 2;
      s += `<g class="gst"><circle class="start" cx="${r1(st.x1)}" cy="${st.y}" r="4.5"/><path class="gw" stroke-width="1.5" d="M${r1(st.x1)} ${st.y}H${xe - 9}"/><path class="gh" d="M${xe} ${st.y}L${xe - 9} ${st.y - 4.2}L${xe - 9} ${st.y + 4.2}Z"/>${st.label ? `<text class="gstart" x="${r1(st.x1 + 10)}" y="${st.y - 9}">${esc(st.label)}</text>` : ""}</g>`;
    }
    for (const f of G.files) {
      const b = G.N[f], x = b.x, y = b.y;
      const tip = `<b>${b.title ? esc(b.title).replace(/`([^`\n]+)`/g, "<code>$1</code>") : `<code>${esc(b.name)}</code>${b.role ? " · " + esc(b.role) : ""}`}</b>${b.entry ? "<br>Holds the entry point" : ""}<br>Files: ${b.files.map(p => `<code>${esc(p)}</code>`).join(", ")}<br>Click to focus on it and its calls`;
      let t = `<rect class="gbox" x="${x}" y="${y}" width="${b.w}" height="${b.h}" rx="12"/><text class="gname" x="${x + 16}" y="${y + 27}">${esc(b.name)}</text>`;
      if (b.entry) { const tx = x + 16 + tw(b.name, MAP.NAME, "mono") + 8; t += `<rect class="gtagbox" x="${r1(tx)}" y="${y + 13}" width="${r1(tw("entry", 13) + 12)}" height="18" rx="9"/><text class="gtag" x="${r1(tx + 6)}" y="${y + 26}">entry</text>`; }
      b.lines.forEach((l, k) => (t += `<text class="grole" x="${x + 16}" y="${y + 47 + k * 18}">${esc(l)}</text>`));
      const yy = y + 42 + b.lines.length * 18;
      if (b.files.length > 1) {
        const label = expLabel(b.files.length, b.open), lw = tw(label, MAP.MIN) + 24, ex = x + b.w - lw - 10;
        t += `<g class="gexp" data-expand="${esc(f)}" role="button" tabindex="0" aria-expanded="${b.open}" aria-label="${b.open ? "Hide" : "Show"} the files of ${esc(b.name)}"><rect x="${r1(ex)}" y="${y + 11}" width="${r1(lw)}" height="22" rx="11"/><text x="${r1(ex + 12)}" y="${y + 26}">${esc(label)}</text></g>`;
        b.flines.forEach((l, k) => (t += `<text class="gfile" x="${x + 16}" y="${yy + 16 + k * 18}">${esc(l)}</text>`));
      }
      s += `<g class="dg-node k-${b.kind}" data-comp="${esc(f)}" data-files="${esc(b.files.join(" "))}" data-tip="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(b.name)}${b.role ? ": " + esc(b.role) : ""}${b.files.length > 1 ? ` (files: ${esc(b.files.join(", "))})` : ""}">${t}</g>`;
    }
    const y = G.keyY;
    let x = 24;
    s += `<g class="dg-key"><line class="sep" x1="16" y1="${y - 24}" x2="${G.W - 16}" y2="${y - 24}"/><circle class="start" cx="${x + 5}" cy="${y - 4}" r="4.5"/><text class="lgt" x="${x + 16}" y="${y}">where a traced flow starts</text>`;
    x += 16 + tw("where a traced flow starts", MAP.MIN) + 28;
    s += `<path class="gw" stroke-width="1.25" d="M${x} ${y - 4}H${x + 22}"/><path class="gw" stroke-width="3.75" d="M${x + 30} ${y - 4}H${x + 52}"/><text class="lgt" x="${x + 60}" y="${y}">heavier = more calls (hover a line for its count)</text></g>`;
    return `<svg class="dg dg-graph dg-map" data-key="graph" data-dir="map" data-view="${view}" data-natural="${G.natural}" data-crossings="${G.crossings[view === "all" ? "all" : "main"]}" data-crossings-main="${G.crossings.main}" data-crossings-all="${G.crossings.all}" data-calls="${G.nCalls}" viewBox="0 0 ${G.W} ${G.H}" width="${G.W}" height="${G.H}" role="group" aria-label="Component map: ${G.files.length} components and the calls between them">${s}</svg>`;
  }
  return { tw, wrapText, edgeOf, lanesOf, layoutSeq, renderSeq, resolver, graphModel, compName, layoutMap, renderMap,
    mainEdges, crossingsOf, D, MAP };
})();
