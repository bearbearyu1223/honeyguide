#!/bin/bash
# Regenerate the refined B SVGs and re-shoot this folder's sheets. Headless Chrome always runs under a 60 s alarm.
D=/Users/someone/Documents/GitHub/honeyguide/assets/logo-concepts/comb/b-refined
C="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
P=${TMPDIR:-/tmp}/hg-logo-chrome-profile
python3 "$D/gen.py" "$@" || exit 1
shot(){ # out size query extra
  perl -e 'alarm 60; exec @ARGV' "$C" --headless=new --disable-gpu --hide-scrollbars --user-data-dir=$P $4 \
    --allow-file-access-from-files --virtual-time-budget=3000 \
    --force-device-scale-factor=1 --screenshot="$D/$1" --window-size="$2" "file://$D/compare.html$3" >/dev/null 2>&1 || echo "fail $1"
}
shot compare-light.png 1240,1010 ""
shot compare-dark.png 1240,1010 "?theme=dark" --force-dark-mode
shot in-context-light.png 1000,300 "?view=context"
shot in-context-dark.png 1000,300 "?view=context&theme=dark" --force-dark-mode
