#!/bin/bash
D="$(cd "$(dirname "$0")" && pwd)"
C="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
P=${TMPDIR:-/tmp}/hg-logo-chrome-profile
shot(){ # out size query extra
  perl -e 'alarm 60; exec @ARGV' "$C" --headless=new --disable-gpu --hide-scrollbars --user-data-dir=$P $4 \
    --force-device-scale-factor=1 --screenshot="$D/$1" --window-size="$2" "file://$D/compare.html$3" >/dev/null 2>&1 || echo "fail $1"
}
shot compare-light.png 1000,720 ""
shot compare-dark.png 1000,720 "?theme=dark" --force-dark-mode
shot in-context-light.png 1240,330 "?view=context"
shot in-context-dark.png 1240,330 "?view=context&theme=dark" --force-dark-mode
