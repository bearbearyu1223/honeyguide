#!/bin/sh
# Render the avatar PNGs, frames and animated GIF/APNG from sheet.html (headless Chrome, 60 s timeout per shot).
# Run from anywhere: sh assets/avatars/tools/render_pngs.sh   (needs Google Chrome and ffmpeg; nothing else)
set -e
cd "$(dirname "$0")/.."
D="$PWD"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
shot() { # out WxH query [virtual ms]
  perl -e 'alarm 60; exec @ARGV' "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --allow-file-access-from-files --user-data-dir="$T/prof" --screenshot="$1" --window-size="$2" --virtual-time-budget="${4:-400}" \
    "file://$D/sheet.html?$3" 2>/dev/null || { echo "chrome failed or timed out: $1" >&2; exit 1; }
}
# sheets: reduced motion gives every state its still pose, so the PNG shows each state clearly
shot sheet-light.png 1340,1690 "motion=reduce"
shot sheet-dark.png 1340,1690 "motion=reduce&theme=dark"
shot context-light.png 1340,400 "view=context" 1000
shot context-dark.png 1340,400 "view=context&theme=dark" 1000
mkdir -p frames anim
# anim <agent> <state> <period s> <out name>: a 20 fps loop as GIF and APNG. Cells are laid out 10 per row so long
# loops (Honey's 5 s doze) stay within Chrome's screenshot size.
anim() {
  N=$(python3 -c "print(round($3*20))")
  C=$(( N < 10 ? N : 10 )); R=$(( (N + C - 1) / C ))
  TS=$(python3 -c "print(','.join(f'{i*$3/$N:.4f}' for i in range($N)))")
  shot "$T/s.png" "$((C*112)),$((R*112))" "strip=$1&state=$2&cols=$C&ts=$TS"
  ffmpeg -y -loglevel error -i "$T/s.png" -vf "untile=${C}x${R},trim=end_frame=$N,setpts=N/(20*TB),split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=none" -r 20 -loop 0 "anim/$4.gif"
  ffmpeg -y -loglevel error -i "$T/s.png" -vf "untile=${C}x${R},trim=end_frame=$N,setpts=N/(20*TB)" -r 20 -plays 0 -f apng "anim/$4.png"
  echo "$4: $N-frame loop"
}
# agent  period(s)  four key times (s) for the still frames (working)
while read -r A P K; do
  shot "$T/k.png" 448,112 "strip=$A&ts=$K"
  ffmpeg -y -loglevel error -i "$T/k.png" -vf "untile=4x1" -start_number 1 "frames/$A-%d.png"
  anim "$A" working "$P" "$A-working"
done <<'LIST'
guide 2.4 0.15,0.65,1.5,1.85
cartographer 2.4 0.1,0.7,1.3,2.0
investigator 2.6 0,0.78,1.43,2.03
tracer 1.2 0,0.3,0.6,0.9
checker 1.4 0.1,0.49,0.73,1.0
LIST
# Honey's one-shot landing (it plays once, then holds the content pose; the GIF loops it) and its doze
anim guide done 2.6 honey-done
anim guide waiting 5.0 honey-waiting
