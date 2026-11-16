#!/bin/zsh
# usage: answer.sh <out.jsonl>
# Answers every open question in the nanochat map's inbox with one real batch Claude Code session (the Guide, from the
# frozen plugin copy at honeyguide-run), in place of the Monitor watcher an interactive session would use. Each
# stream-json event is written with the time it was received ({"t": unix, "e": event}), so the terminal
# picture-in-picture can be rendered from what really happened, when it happened.
OUT=$1
W=~/Documents/GitHub/honeyguide-run
export PATH=$W/.venv/bin:$PATH
cd ~/Documents/GitHub/honeyguide-targets/nanochat
claude -p "/honeyguide:honeyguide watch

This is a batch run for a demo recording, in place of the Monitor watcher: answer every open question in the inbox now (SKILL.md section 4: claim, show, route, activity start, dispatch, close), then run the Checker on the new answers in the foreground so it finishes before you stop. Do NOT start a server, the Monitor or honeyguide watch --follow. The CLI is on PATH as \`honeyguide\`. Use flags or --input files only, never pipes or heredocs. Then report in two or three lines." \
  --plugin-dir $W --permission-mode acceptEdits \
  --allowedTools "Bash(honeyguide:*)" "Bash(git:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(wc:*)" "Bash(find:*)" "Read" "Grep" "Glob" "Agent" "Skill" "Write(~/.honeyguide/**)" "Edit(~/.honeyguide/**)" \
  --max-budget-usd 8 --output-format stream-json --verbose 2> ${OUT%.jsonl}.stderr.txt \
  | python3 -u -c 'import sys, json, time
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        e = json.loads(line)
    except ValueError:
        e = {"raw": line}
    print(json.dumps({"t": time.time(), "e": e}), flush=True)' > $OUT
echo ${pipestatus[1]} > ${OUT%.jsonl}.exit
