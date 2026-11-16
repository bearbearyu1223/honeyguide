/* Han's eval chores page: T5 why/how questions, T6a flow hops, T6b callers disputes, Done.
   No inline script or style (CSP); every string from the server goes in as text, never as HTML.
   Every change is posted at once (one queue, in order); the server saves it to eval/human/answers/. */
(function () {
  "use strict";
  var TOKEN = (location.hash.match(/(?:^#|&)t=([0-9a-f]{32})/) || [])[1] || "";
  var S = null;                                   // the server's state
  var ui = {tab: "t5", repo: null, cur: {}};      // cur[repo] = {q, h}: the keyboard cursor on the hops tab
  try {
    ui.tab = localStorage.getItem("hg-eval.tab") || "t5";
    ui.repo = localStorage.getItem("hg-eval.repo");
  } catch (e) { /* storage off */ }
  var main = document.getElementById("main");

  // ---------- small helpers ----------
  function h(tag, attrs) {
    var el = document.createElement(tag);
    for (var k in attrs || {}) {
      var v = attrs[k];
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(el, x); }); return; }
    el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  function ext(href, text, cls) { return h("a", {href: href, target: "_blank", rel: "noopener noreferrer", class: cls}, text); }
  function code(t) { return h("code", {text: t}); }
  function repoOf(name) { return S.repos.filter(function (r) { return r.repo === name; })[0]; }
  function R() { return repoOf(ui.repo); }

  var banner = document.getElementById("banner");
  function showBanner(msg) { banner.textContent = msg; banner.hidden = !msg; }
  var savedEl = document.getElementById("saved"), savedTimer = null;
  function flash(msg, err) {
    savedEl.textContent = msg;
    savedEl.className = "saved on" + (err ? " err" : "");
    clearTimeout(savedTimer);
    if (!err) savedTimer = setTimeout(function () { savedEl.className = "saved"; }, 1400);
  }

  // ---------- server ----------
  function api(path, body) {
    var opts = {headers: {"X-Honeyguide-Token": TOKEN}};
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (j) {
        if (r.status === 403) throw new Error("The server refused the token. Open the URL serve.py printed (it ends in #t=...); a restarted server prints a new one.");
        if (!j.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    });
  }
  var chain = Promise.resolve(), pending = 0;
  function post(path, body) {           // one queue: changes reach the server in the order they were made
    pending++;
    flash("Saving...");
    var p = chain.then(function () { return api(path, body); });
    chain = p.then(function () {
      if (--pending === 0) flash("Saved");
    }, function (e) {
      pending--;
      flash("Not saved: " + e.message, true);
      showBanner("Not saved: " + e.message);
    });
    return p;
  }

  // ---------- counts ----------
  function hopCounts(r) {
    var m = 0, t = 0;
    r.flows.forEach(function (q) { r.marks[q.id].forEach(function (x) { t++; if (x) m++; }); });
    return {marked: m, total: t};
  }
  function disputeCounts(r) {
    var d = 0, t = 0;
    r.callers.forEach(function (q) { r.decisions[q.id].forEach(function (x) { t++; if (x.decision) d++; }); });
    return {decided: d, total: t};
  }
  function whyProblems(q) {
    var out = [], n = q.rubric_must.filter(function (b) { return b.trim(); }).length;
    var b = S.bounds.rubric;
    if (!q.text.trim()) out.push("no question text");
    if (n < b[0] || n > b[1]) out.push("rubric has " + n + " bullet" + (n === 1 ? "" : "s") + " (needs " + b[0] + "-" + b[1] + ")");
    return out;
  }

  // ---------- frame: tabs, repo switch ----------
  function setTab(t) {
    ui.tab = t;
    try { localStorage.setItem("hg-eval.tab", t); } catch (e) { /* */ }
    render();
  }
  function setRepo(name) {
    ui.repo = name;
    try { localStorage.setItem("hg-eval.repo", name); } catch (e) { /* */ }
    render();
  }
  document.querySelectorAll(".tabs button").forEach(function (b) {
    b.addEventListener("click", function () { setTab(b.dataset.tab); });
  });
  var themeBtn = document.getElementById("theme");
  function themeLabel() { themeBtn.textContent = document.documentElement.dataset.theme === "dark" ? "Light" : "Dark"; }
  themeBtn.addEventListener("click", function () {
    var d = document.documentElement, t = d.dataset.theme === "dark" ? "light" : "dark";
    d.dataset.theme = t;
    try { localStorage.setItem("hg-eval.theme", t); } catch (e) { /* */ }
    themeLabel();
  });
  themeLabel();

  function repoSwitch(countOf) {
    return h("div", {class: "seg", role: "group", "aria-label": "Repo"}, S.repos.map(function (r) {
      return h("button", {type: "button", "aria-pressed": String(r.repo === ui.repo), "data-repo": r.repo,
                          onclick: function () { setRepo(r.repo); }},
               r.repo, h("span", {class: "n", text: countOf(r)}));
    }));
  }
  function pinLinks(r) {
    return h("div", {class: "links"},
             ext(r.tree, ["Code at ", code(r.commit.slice(0, 7)), " ↗"]),
             ext(r.readme, "README ↗"));
  }
  function progress(text, value, max, id) {
    return h("div", {class: "prog"}, h("progress", {value: value, max: max || 1}), h("span", {id: id, text: text}));
  }

  function render() {
    document.querySelectorAll(".tabs button").forEach(function (b) {
      b.setAttribute("aria-selected", String(b.dataset.tab === ui.tab));
    });
    var y = window.scrollY;               // a re-render keeps the reader where they were
    main.textContent = "";
    var stale = Object.keys(S.stale);
    if (stale.length && !banner.dataset.err) {
      showBanner("The frozen question sets changed since these answers were saved (" + stale.join(", ") +
                 "). Marks were kept only where the hop or call site is unchanged; please re-check them.");
    }
    ({t5: renderWhy, hops: renderHops, callers: renderCallers, done: renderDone}[ui.tab] || renderWhy)();
    if (ui.tab === ui.lastTab) window.scrollTo(0, y); else window.scrollTo(0, 0);
    ui.lastTab = ui.tab;
  }

  // ---------- T5 why/how ----------
  var whyTimer = {};
  function saveWhy(r) {                  // autosave: debounce typing, then post the whole list in Han's order
    clearTimeout(whyTimer[r.repo]);
    whyTimer[r.repo] = setTimeout(function () { postWhy(r); }, 400);
    flash("Editing...");
  }
  function postWhy(r) {
    clearTimeout(whyTimer[r.repo]);
    return post("/api/whyhow", {repo: r.repo, questions: r.whyhow});
  }
  function whyCountText(r) {
    var b = S.bounds.whyhow;
    return r.repo + ": " + r.whyhow.length + " question" + (r.whyhow.length === 1 ? "" : "s") +
           " (about " + S.bounds.target + "; " + b[0] + "-" + b[1] + " allowed)";
  }
  function renderWhy() {
    var r = R();
    add(main, [
      h("h1", {text: "T5: why and how questions"}),
      h("p", {class: "lede", text: "About " + S.bounds.target + " per repo, each with a short rubric: what a good answer must say (" +
              S.bounds.rubric[0] + "-" + S.bounds.rubric[1] + " points), and if you like what earns partial credit and what is wrong."}),
      h("div", {class: "note", id: "reminder"}, h("b", {text: "Reminder. "}), S.reminder),
      h("div", {class: "pins"}, S.repos.map(function (x) {
        return [h("span", {class: "r", text: x.repo}),
                ext(x.tree, ["GitHub at ", code(x.commit.slice(0, 7)), " ↗"]),
                ext(x.readme, "README ↗"), h("span")];
      })),
      h("div", {class: "reporow"},
        repoSwitch(function (x) { return String(x.whyhow.length); }),
        h("span", {class: "count" + (r.whyhow.length >= S.bounds.whyhow[0] && r.whyhow.length <= S.bounds.whyhow[1] ? " ok" : ""),
                   id: "whycount", text: whyCountText(r)}))
    ]);
    var list = h("div", {id: "whylist"});
    r.whyhow.forEach(function (q, i) { list.appendChild(whyCard(r, q, i)); });
    add(main, list);
    add(main, h("div", {class: "adds"},
      h("button", {type: "button", class: "btn primary", id: "addwhy", disabled: r.whyhow.length >= 40,
                   onclick: function () { addWhy(r); }}, "Add a question")));
  }
  function addWhy(r) {
    post("/api/whyhow/add", {repo: r.repo}).then(function (j) {
      r.whyhow.push(j.question);
      render();
      var cards = document.querySelectorAll("#whylist .wq");
      var last = cards[cards.length - 1];
      if (last) { last.scrollIntoView({block: "center"}); last.querySelector("textarea.q").focus(); }
    }, function () { /* the queue reported it */ });
  }
  function whyCard(r, q, i) {
    var probs = whyProblems(q);
    var st = h("span", {class: "wq-st" + (probs.length ? " todo" : ""), text: probs.length ? probs.join("; ") : "complete"});
    function refreshStatus() {
      var p = whyProblems(q);
      st.className = "wq-st" + (p.length ? " todo" : "");
      st.textContent = p.length ? p.join("; ") : "complete";
    }
    function field(label, hint, key, multi, cls) {
      var el = multi ? h("textarea", {rows: 2, class: cls, "data-k": key}) : h("input", {type: "text", "data-k": key});
      el.value = q[key];
      el.addEventListener("input", function () { q[key] = el.value; refreshStatus(); saveWhy(r); });
      return [h("label", {class: "fl"}, label, hint ? h("span", {class: "hint", text: hint}) : null), el];
    }
    function move(d) {
      var j = i + d;
      if (j < 0 || j >= r.whyhow.length) return;
      r.whyhow.splice(j, 0, r.whyhow.splice(i, 1)[0]);
      postWhy(r);
      render();
      var b = document.querySelectorAll("#whylist .wq")[j];
      if (b) b.querySelector(d < 0 ? ".up" : ".down").focus();
    }
    var del = h("button", {type: "button", class: "ibtn danger", text: "Delete"});
    var armTimer = null;
    del.addEventListener("click", function () {
      if (!del.classList.contains("armed")) {
        del.classList.add("armed");
        del.textContent = "Delete? Click again";
        armTimer = setTimeout(function () { del.classList.remove("armed"); del.textContent = "Delete"; }, 4000);
        return;
      }
      clearTimeout(armTimer);
      r.whyhow.splice(i, 1);
      postWhy(r);
      render();
    });
    var bullets = h("div", {class: "buls"});
    q.rubric_must.forEach(function (b, k) {
      var inp = h("input", {type: "text", value: b, "aria-label": "Rubric point " + (k + 1), placeholder: "A good answer says..."});
      inp.addEventListener("input", function () { q.rubric_must[k] = inp.value; refreshStatus(); saveWhy(r); });
      bullets.appendChild(h("div", {class: "bul"}, h("span", {class: "dot"}), inp,
        h("button", {type: "button", class: "ibtn", "aria-label": "Remove point " + (k + 1), text: "×",
                     onclick: function () { q.rubric_must.splice(k, 1); postWhy(r); render(); }})));
    });
    var maxB = S.bounds.rubric[1];
    return h("div", {class: "card wq", "data-id": q.id},
      h("div", {class: "wq-h"},
        h("span", {class: "wq-n", text: "Question " + (i + 1)}), h("span", {class: "wq-id", text: q.id}), st,
        h("span", {class: "sp"}),
        h("button", {type: "button", class: "ibtn up", "aria-label": "Move up", disabled: i === 0, onclick: function () { move(-1); }}, "↑"),
        h("button", {type: "button", class: "ibtn down", "aria-label": "Move down", disabled: i === r.whyhow.length - 1, onclick: function () { move(1); }}, "↓"),
        del),
      field("Question", "about " + r.repo, "text", true, "q"),
      h("label", {class: "fl"}, "A good answer must say", h("span", {class: "hint", text: S.bounds.rubric[0] + "-" + maxB + " points"})),
      bullets,
      h("button", {type: "button", class: "ibtn addb", disabled: q.rubric_must.length >= maxB,
                   onclick: function () {
                     q.rubric_must.push(""); postWhy(r); render();
                     var c = document.querySelector('.wq[data-id="' + q.id + '"] .bul:last-child input');
                     if (c) c.focus();
                   }}, "+ Add a point"),
      field("Partial credit", "optional", "rubric_partial", true),
      field("Wrong", "optional: what a wrong answer says", "rubric_wrong", true),
      field("Relevant files or lines", "optional, free text", "relevant", false));
  }

  // ---------- T6a flow hops ----------
  function hopProgressText(r) {
    var c = hopCounts(r);
    return r.repo + " " + c.marked + " of " + c.total + " hops marked";
  }
  function cursor(r) {
    var c = ui.cur[r.repo];
    if (!c) {
      c = {q: 0, h: 0};
      outer: for (var qi = 0; qi < r.flows.length; qi++) {        // start at the first unmarked hop
        for (var hi = 0; hi < r.flows[qi].hops.length; hi++) {
          if (!r.marks[r.flows[qi].id][hi]) { c = {q: qi, h: hi}; break outer; }
        }
      }
      ui.cur[r.repo] = c;
    }
    return c;
  }
  function renderHops() {
    var r = R(), c = hopCounts(r);
    add(main, [
      h("h1", {text: "T6: flow hops"}),
      h("p", {class: "intro", text: r.flow_intro}),
      h("div", {class: "keys"},
        h("span", null, h("kbd", {text: "↑"}), h("kbd", {text: "↓"}), "move"),
        h("span", null, h("kbd", {text: "←"}), h("kbd", {text: "→"}), "previous / next question"),
        h("span", null, h("kbd", {text: "R"}), "required"),
        h("span", null, h("kbd", {text: "O"}), "optional"),
        h("span", null, h("kbd", {text: "X"}), "excluded (out of the question's scope)"),
        h("span", null, h("kbd", {text: "⌫"}), "unmark"),
        h("span", null, h("kbd", {text: "N"}), "next question")),
      h("div", {class: "reporow"},
        repoSwitch(function (x) { var k = hopCounts(x); return k.marked + "/" + k.total; }),
        pinLinks(r),
        progress(hopProgressText(r), c.marked, c.total, "hopprog"))
    ]);
    var cur = cursor(r);
    r.flows.forEach(function (q, qi) {
      var marks = r.marks[q.id], n = marks.filter(Boolean).length;
      var list = h("ol", {class: "hops"});
      q.hops.forEach(function (hp, hi) {
        list.appendChild(hopRow(r, q, qi, hp, hi, cur));
      });
      add(main, h("section", {class: "card fq" + (qi === cur.q ? " cur" : ""), "data-q": q.id},
        h("div", {class: "fq-h"}, h("span", {class: "fq-id", text: q.id}), h("span", {class: "fq-ph", text: q.phase}),
          h("span", {class: "fq-c" + (n === marks.length ? " ok" : ""), text: n + " of " + marks.length + " marked"})),
        h("p", {class: "fq-t", text: q.text}),
        list));
    });
  }
  function hopRow(r, q, qi, hp, hi, cur) {
    var mark = r.marks[q.id][hi];
    var where = h("span", {class: "where"}, ext(hp.link, hp.file + ":" + hp.line));
    hp.tags.forEach(function (t) {
      where.appendChild(h("span", {class: "tag" + (t[0] === "x" ? " calls" : t[0] === "[" ? " thread" : ""), text: t}));
    });
    function choice(cls, m) {
      return h("button", {type: "button", class: cls, "aria-pressed": String(mark === m), "data-mark": m,
                          title: S.mark_meanings ? S.mark_meanings[m] : m,
                          onclick: function () { ui.cur[r.repo] = {q: qi, h: hi}; markHop(r, qi, hi, mark === m ? null : m, false); }},
        m);
    }
    return h("li", {class: "hop" + (qi === cur.q && hi === cur.h ? " cur" : "") + (mark === "excluded" ? " excluded" : ""),
                    "data-q": q.id, "data-i": hi,
                    onclick: function (e) { if (e.target.closest("a,button")) return; ui.cur[r.repo] = {q: qi, h: hi}; render(); }},
      h("span", {class: "ix", text: String(hi + 1)}),
      h("span", {class: "tg", role: "group", "aria-label": "Mark " + hp.qual},
        choice("a", "required"), choice("b", "optional"), choice("x", "excluded")),
      h("span", {class: "fn"}, code(hp.qual),
        hp.first_caller ? h("span", {class: "from", text: "first called from " + hp.first_caller}) : null),
      where);
  }
  function markHop(r, qi, hi, mark, advance) {
    var q = r.flows[qi];
    r.marks[q.id][hi] = mark;
    post("/api/hop", {repo: r.repo, qid: q.id, index: hi, mark: mark}).catch(function () { /* reported */ });
    if (advance && hi < q.hops.length - 1) ui.cur[r.repo] = {q: qi, h: hi + 1};
    render();
    scrollCur();
  }
  function scrollCur() {
    var el = document.querySelector(".hop.cur");
    if (el) el.scrollIntoView({block: "nearest"});
  }
  function moveCur(r, dq, dh) {
    var c = cursor(r), qi = c.q, hi = c.h;
    if (dq) {
      qi = Math.max(0, Math.min(r.flows.length - 1, qi + dq));
      var m = r.marks[r.flows[qi].id];
      hi = Math.max(0, m.indexOf(null));             // the question's first unmarked hop (else its first)
    } else {
      hi += dh;
      if (hi < 0) { if (qi > 0) { qi--; hi = r.flows[qi].hops.length - 1; } else hi = 0; }
      else if (hi >= r.flows[qi].hops.length) { if (qi < r.flows.length - 1) { qi++; hi = 0; } else hi--; }
    }
    ui.cur[r.repo] = {q: qi, h: hi};
    render();
    var el = document.querySelector(dq ? '.fq.cur' : ".hop.cur");
    if (el) el.scrollIntoView({block: dq ? "start" : "nearest"});
  }
  document.addEventListener("keydown", function (e) {
    if (!S || ui.tab !== "hops" || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.target.closest && e.target.closest("input,textarea,select")) return;
    var r = R(), c = cursor(r), k = e.key;
    if (k === "ArrowDown") moveCur(r, 0, 1);
    else if (k === "ArrowUp") moveCur(r, 0, -1);
    else if (k === "ArrowRight" || k === "n" || k === "N") moveCur(r, 1, 0);
    else if (k === "ArrowLeft") moveCur(r, -1, 0);
    else if (k === "r" || k === "R") markHop(r, c.q, c.h, "required", true);
    else if (k === "o" || k === "O") markHop(r, c.q, c.h, "optional", true);
    else if (k === "x" || k === "X") markHop(r, c.q, c.h, "excluded", true);
    else if (k === "Backspace" || k === "Delete") markHop(r, c.q, c.h, null, false);
    else return;
    e.preventDefault();
  });

  // ---------- T6b callers disputes ----------
  function disputeProgressText(r) {
    var c = disputeCounts(r);
    return r.repo + " " + c.decided + " of " + c.total + " disputed call sites decided";
  }
  var noteTimer = {};
  function renderCallers() {
    var r = R(), c = disputeCounts(r);
    add(main, [
      h("h1", {text: "T6: callers disputes"}),
      h("p", {class: "intro", text: r.disputes_intro}),
      h("ul", {class: "kinds"}, Object.keys(r.dispute_kinds).map(function (k) {
        return h("li", null, h("b", {text: k}), r.dispute_kinds[k]);
      })),
      h("div", {class: "reporow"},
        repoSwitch(function (x) { var k = disputeCounts(x); return k.decided + "/" + k.total; }),
        pinLinks(r),
        progress(disputeProgressText(r), c.decided, c.total, "disprog"))
    ]);
    var withD = r.callers.filter(function (q) { return q.disputes.length; });
    var without = r.callers.filter(function (q) { return !q.disputes.length; });
    withD.forEach(function (q) { add(main, callersCard(r, q)); });
    if (without.length) {
      add(main, h("h2", {class: "sub", text: "Nothing to decide (" + without.length + " questions): the key, for reference"}));
      without.forEach(function (q) { add(main, callersCard(r, q)); });
    }
  }
  function howFound(c) {
    var s = {both: "AST + trace", ast: "AST", trace: "trace"}[c.source] || c.source;
    if (c.ast_via.length) s += " (" + c.ast_via.join(", ") + ")";
    return s;
  }
  function callersCard(r, q) {
    var dec = r.decisions[q.id];
    var n = dec.filter(function (d) { return d.decision; }).length;
    var body = h("div", {class: "cq-body"});
    add(body, h("div", {class: "sub", text: "In the key (" + q.in_key.length + "), read-only"}));
    add(body, q.in_key.length ? h("ul", {class: "inkey"}, q.in_key.map(function (k) {
      return h("li", null, h("span", {class: "how", text: howFound(k)}), code(k.qual),
               k.link ? ext(k.link, k.file + (k.lines.length ? ":" + k.lines[0] : "")) : h("span", {text: k.file}),
               k.also_accept.length ? h("span", {class: "muted", text: "also accepted: " + k.also_accept.join(", ")}) : null);
    })) : h("p", {class: "cq-t", text: "No callers in the key."}));
    if (q.disputes.length) add(body, h("div", {class: "sub", text: "To decide (" + q.disputes.length + ")"}));
    q.disputes.forEach(function (d, i) {
      var a = dec[i];
      function decide(v) {
        a.decision = a.decision === v ? null : v;
        post("/api/dispute", {repo: r.repo, qid: q.id, index: i, decision: a.decision, note: a.note}).catch(function () {});
        render();
      }
      var note = h("input", {type: "text", maxlength: 300, placeholder: "Note (optional, one line)", value: a.note,
                             "aria-label": "Note on " + d.caller});
      note.addEventListener("input", function () {
        a.note = note.value.replace(/\n/g, " ");
        var key = q.id + "/" + i;
        clearTimeout(noteTimer[key]);
        flash("Editing...");
        noteTimer[key] = setTimeout(function () {
          post("/api/dispute", {repo: r.repo, qid: q.id, index: i, decision: a.decision, note: a.note}).catch(function () {});
        }, 400);
      });
      add(body, h("div", {class: "dsp" + (a.decision ? " decided" : ""), "data-q": q.id, "data-i": i},
        h("div", {class: "dsp-h"}, code(d.caller), h("span", {class: "file", text: d.file}),
          h("span", {class: "tg", role: "group", "aria-label": "Is " + d.caller + " a caller?"},
            h("button", {type: "button", class: "a", "aria-pressed": String(a.decision === "caller"), "data-d": "caller",
                         onclick: function () { decide("caller"); }}, "caller"),
            h("button", {type: "button", class: "b", "aria-pressed": String(a.decision === "not"), "data-d": "not",
                         onclick: function () { decide("not"); }}, "not"))),
        h("div", {class: "dsp-l"},
          d.kinds.map(function (k) { return h("span", {class: "tag", title: r.dispute_kinds[k] || "", text: k}); }),
          h("span", null, "name ", code(d.name)),
          d.only_repo_def ? h("span", {text: "only repo def named so"}) : null,
          h("span", {text: d.lines.length > 1 ? "lines" : "line"}),
          d.links.map(function (l) { return ext(l.href, String(l.line)); })),
        note));
    });
    return h("section", {class: "card cq" + (q.disputes.length ? "" : " zero"), "data-q": q.id},
      h("div", {class: "fq-h"}, h("span", {class: "fq-id", text: q.id}), code(q.target),
        ext(q.target_link, q.target_file + ":" + q.target_line, "fq-ph"),
        h("span", {class: "fq-c" + (n === q.disputes.length ? " ok" : ""),
                   text: q.in_key.length + " in the key, " + (q.disputes.length ? n + " of " + q.disputes.length + " decided" : "0 to decide")})),
      body);
  }

  // ---------- Done ----------
  function renderDone() {
    add(main, [h("h1", {text: "Done?"}),
               h("p", {class: "lede", text: "What is complete and what is left, read back from the saved files (the same summary eval/human/check.py prints)."})]);
    var box = h("div", null, h("p", {class: "muted", text: "Reading the saved files..."}));
    add(main, box);
    var go = function () {
      api("/api/summary").then(function (j) {
        if (ui.tab !== "done") return;
        box.textContent = "";
        var s = j.summary;
        Object.keys(s.repos).forEach(function (name) {
          var v = s.repos[name], w = v.whyhow, hp = v.hops, d = v.disputes;
          function row(ok, k, text, left) {
            return h("div", {class: "dn-r"}, h("span", {class: "ic" + (ok ? " ok" : ""), text: ok ? "✓" : "○"}),
                     h("span", {class: "k", text: k}), h("div", null, text, left && left.length ? h("ul", null, left.map(function (x) { return h("li", {text: x}); })) : null));
          }
          var wl = w.left.map(function (q) { return q.id + ": " + q.problems.join("; "); });
          if (!w.count_ok) wl.unshift((w.count < S.bounds.whyhow[0] ? "add" : "remove") + " questions to reach " + S.bounds.whyhow.join("-"));
          add(box, h("section", {class: "card dn", "data-repo": name},
            h("h2", null, name, h("span", {class: "dn-st" + (v.done ? " ok" : ""), text: v.done ? "complete" : "not complete"})),
            row(w.done, "T5 why/how", w.count + (w.count === 1 ? " question, " : " questions, ") + w.complete + " with text and a rubric", wl),
            row(hp.done, "T6 flow hops", name + " " + hp.marked + " of " + hp.total + " hops marked",
                hp.questions.filter(function (q) { return q.marked < q.total; }).map(function (q) { return q.id + ": " + (q.total - q.marked) + " of " + q.total + " unmarked"; })),
            row(d.done, "T6 callers", d.decided + " of " + d.total + " disputed call sites decided",
                d.questions.filter(function (q) { return q.open.length; }).map(function (q) { return q.id + " (" + q.target + "): " + q.open.join(", "); })),
            v.stale_files.length ? row(false, "Stale", "recorded against another MANIFEST.txt", v.stale_files) : null));
        });
        add(box, h("details", {class: "raw"}, h("summary", {text: "As check.py prints it"}), h("pre", {text: j.text})));
      }, function (e) { box.textContent = e.message; });
    };
    chain.then(go, go);                  // after any save still in flight
  }

  // ---------- start ----------
  if (!TOKEN) {
    main.textContent = "";
    add(main, [h("h1", {text: "Open the URL the server printed"}),
               h("p", {class: "lede", text: "This page needs its token: run uv run python eval/human/serve.py and open the URL it prints (it ends in #t=...)."})]);
    document.documentElement.dataset.ready = "1";
    return;
  }
  api("/api/state").then(function (s) {
    S = s;
    if (!repoOf(ui.repo)) ui.repo = S.repos[0].repo;
    render();
    document.documentElement.dataset.ready = "1";
  }, function (e) {
    main.textContent = "";
    add(main, [h("h1", {text: "Can't load the chores"}), h("p", {class: "lede", text: e.message})]);
    document.documentElement.dataset.ready = "1";
  });
})();
