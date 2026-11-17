"""Screenshot each tab of the chores page into eval/human/screens/ (light; ``--dark`` adds dark ones).

    uv run python eval/human/shoot.py [--dark]

Runs its own server on a free port with a throwaway answers directory (a few sample marks and one sample why/how
question, labelled as a sample), so the real answers in eval/human/answers/ are never touched. Chrome runs under
``perl -e 'alarm N; exec @ARGV'`` (tests/cdp.py).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tests"))
import chores  # noqa: E402
import serve  # noqa: E402
from cdp import Chrome  # noqa: E402

SCREENS = HERE / "screens"


def seed(answers: chores.Answers) -> None:
    item = answers.add_whyhow("nanochat")
    answers.save_whyhow("nanochat", [dict(item, text="(screenshot sample) A why/how question the annotator writes goes here.",
                                          rubric_must=["a first point a good answer must make", ""],
                                          relevant="(free text, optional)")])
    for i, mark in enumerate(["required", "required", "optional"]):
        answers.set_hop("nanochat", "nc-flo-01", i, mark)
    answers.set_dispute("nanochat", "nc-cal-07", 0, "not", "(screenshot sample note)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dark", action="store_true")
    args = ap.parse_args(argv)
    SCREENS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        answers = chores.Answers(Path(tmp))
        seed(answers)
        server = serve.make_server(answers, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/#t={server.RequestHandlerClass.token}"
        try:
            with Chrome(width=1280, height=900, alarm=60) as c:
                for dark in ([False, True] if args.dark else [False]):
                    c.media(dark=dark)
                    c.goto(url)
                    c.js("localStorage.clear()")
                    for tab in ("t5", "hops", "callers", "done"):
                        c.js(f"document.querySelector('[data-tab={tab}]').click()")
                        if tab == "done":
                            c.wait("document.querySelector('.dn') !== null")
                        c.js("new Promise(r => setTimeout(r, 250))")
                        out = SCREENS / f"{tab}{'-dark' if dark else ''}.png"
                        c.screenshot(out)
                        print(out)
                    errors = c.console_errors()
                    if errors:
                        print("console errors:", errors, file=sys.stderr)
                        return 1
        finally:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
