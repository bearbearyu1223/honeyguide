"""Title, install, run-clock and closing cards: HTML rendered by headless Chrome (1440x900 at 2x) to PNG.

    uv run --project .. python cards.py OUT_DIR

The run-clock numbers are quoted from outputs/runs.txt (run 2, the repair pass and the re-check of the nanochat map);
nothing on a card is typed from memory.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path

from rec import Chrome

HG = Path(__file__).resolve().parent.parent
LOGO = (HG / "assets/logo-dark.svg").read_text()
ICON = (HG / "assets/icon-dark.svg").read_text()

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1440px;height:900px;background:#171A20;color:#F0F1F3;font-family:-apple-system,"Helvetica Neue",Arial,sans-serif}
.c{width:1440px;height:900px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;text-align:center}
.logo svg{width:620px;height:auto}
.prom{font-size:40px;font-weight:600;letter-spacing:-.01em}
.sub{font-size:24px;color:#A5AAB5;max-width:1000px;line-height:1.45}
.k{font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:#E2C25C;font-weight:600}
pre{font-family:Menlo,monospace;font-size:24px;line-height:1.6;text-align:left;background:#1F232A;border:1px solid #323741;
    border-radius:12px;padding:22px 30px;color:#F0F1F3;white-space:pre}
pre .p{color:#7F8590} pre .a{color:#E2C25C} pre .c2{color:#7F8590}
.row{display:flex;gap:36px;align-items:stretch}
.clock{display:flex;gap:28px}
.ck{background:#1F232A;border:1px solid #323741;border-radius:16px;padding:24px 32px;min-width:340px}
.ck .n{font-size:68px;font-weight:700;color:#E2C25C;font-variant-numeric:tabular-nums}
.ck .l{font-size:22px;color:#D2D5DB;margin-top:6px}
.ck .s{font-size:18px;color:#A5AAB5;margin-top:10px}
.foot{font-size:18px;color:#7F8590}
.url{font-family:Menlo,monospace;font-size:30px;color:#F0F1F3}
.soon{font-size:20px;color:#E2C25C;margin-left:10px}
"""


def page(body: str) -> str:
    return f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body><div class=c>{body}</div></body></html>"


def runs_txt(path: Path) -> dict:
    """nanochat's run 2, repair and re-check rows (wall minutes, cost at API list price) and its map's Checker
    verdicts after the re-check, quoted from outputs/runs.txt (the deterministic capture of the run records)."""
    t = path.read_text()
    run2 = re.search(r"nanochat\s+run 2\s+([\d.]+)\s+\S+\s+\$([\d.]+)", t)
    rep = re.search(r"nanochat\s+repair\s+([\d.]+)\s+\S+\s+\$([\d.]+)", t)
    rck = re.search(r"\nrecheck\n.*?nanochat\s+([\d.]+)\s+\d+\s+\$([\d.]+)", t, re.S)
    after = re.search(r"nanochat, run 2 after re-check.*?claims\s+(\d+)\s+Checker verdicts\s+supported (\d+), not supported (\d+)",
                      t, re.S)
    return {"ex": (float(run2[1]), float(run2[2])), "rp": (float(rep[1]), float(rep[2])), "rc": (float(rck[1]), float(rck[2])),
            "claims": int(after[1]), "ok": int(after[2]), "bad": int(after[3])}


def cards(runs: Path) -> dict[str, str]:
    r = runs_txt(runs)
    (ex_min, ex_cost), (rp_min, rp_cost), (rc_min, rc_cost) = r["ex"], r["rp"], r["rc"]
    return {
        "title": page(f"""<div class=logo>{LOGO}</div>
          <div class=prom>Learn a repo as a map. Ask it questions.</div>
          <div class=sub>Claude Code subagents read the code and write a map you read in your browser.
          Every sentence cites the lines it comes from.</div>"""),
        "install": page("""<div class=k>Install (from the README)</div>
          <pre><span class=c2># the CLI</span>
<span class=p>$</span> uv tool install --editable ~/honeyguide

<span class=c2># the plugin, in Claude Code</span>
<span class=p>&gt;</span> /plugin marketplace add /path/to/honeyguide
<span class=p>&gt;</span> /plugin install honeyguide@honeyguide

<span class=c2># then, in the repo you want to learn</span>
<span class=p>&gt;</span> <span class=a>/honeyguide:honeyguide explore</span></pre>"""),
        "clock": page(f"""<div class=k>How this map was made</div>
          <pre style="font-size:20px"><span class=p>~/…/nanochat $</span> claude -p <span class=a>"/honeyguide:honeyguide start over</span>
  <span class=a>This is a batch run while the user is away …"</span> --plugin-dir … --max-budget-usd 40</pre>
          <div class=clock>
            <div class=ck><div class=n>{ex_min:.0f} min</div><div class=l>explore, then the Checker</div>
              <div class=s>${ex_cost:.2f} at API list price</div></div>
            <div class=ck><div class=n>+{rp_min:.0f} min</div><div class=l>repair pass</div>
              <div class=s>${rp_cost:.2f} at API list price</div></div>
            <div class=ck><div class=n>+{rc_min:.0f} min</div><div class=l>re-check: compute, don't quote</div>
              <div class=s>${rc_cost:.2f} at API list price</div></div>
          </div>
          <div class=sub>{r["claims"]} claims about the code. After the re-check, the Checker passes {r["ok"]};
          {r["bad"]} are flagged "Needs a look".</div>
          <div class=foot>Batch runs of the same skill, on a Claude subscription. Not replayed here. Source: outputs/runs.txt</div>"""),
        "close": page(f"""<div class=logo>{LOGO}</div>
          <pre style="font-size:22px"><span class=p>$</span> uv tool install --editable ~/honeyguide
<span class=p>&gt;</span> /plugin install honeyguide@honeyguide
<span class=p>&gt;</span> <span class=a>/honeyguide:honeyguide explore</span></pre>
          <div><span class=url>github.com/bearbearyu1223/honeyguide</span><span class=soon>public soon</span></div>"""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--runs", default=str(HG / "outputs/runs.txt"), help="outputs/runs.txt (the run receipts)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with Chrome(alarm=120) as c:
        for name, html in cards(Path(a.runs)).items():
            f = out / f"{name}.html"
            f.write_text(html)
            c.call("Page.navigate", url=f.as_uri())
            c.wait("document.readyState === 'complete'")
            data = c.call("Page.captureScreenshot", format="png")["data"]
            (out / f"{name}.png").write_bytes(base64.b64decode(data))
            print(name)


if __name__ == "__main__":
    main()
