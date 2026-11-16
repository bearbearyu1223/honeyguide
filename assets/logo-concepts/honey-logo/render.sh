#!/bin/bash
# Regenerate Honey's logo set (build_avatars.py) and re-shoot this folder's sheets. Headless Chrome always runs
# under a 60 s alarm.
D="$(cd "$(dirname "$0")" && pwd)"
C="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
P="$(mktemp -d)"; trap 'rm -rf "$P"' EXIT
python3 "$D/../../avatars/tools/build_avatars.py" || exit 1
shot(){ # out size query extra
  perl -e 'alarm 60; exec @ARGV' "$C" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$P" $4 \
    --allow-file-access-from-files --virtual-time-budget=3000 \
    --force-device-scale-factor=1 --screenshot="$D/$1" --window-size="$2" "file://$D/compare.html$3" >/dev/null 2>&1 || echo "fail $1"
}
shot compare-light.png 1180,990 ""
shot compare-dark.png 1180,990 "?theme=dark" --force-dark-mode
shot in-context-light.png 1020,300 "?view=context"
shot in-context-dark.png 1020,300 "?view=context&theme=dark" --force-dark-mode
