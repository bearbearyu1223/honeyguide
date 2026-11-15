# Honeyguide

Claude Code subagents that learn a codebase into a source-cited map you read in the browser, and answer the
questions you highlight on it. Plus an eval of whether the map pays off. Work in progress; the plan is in
research-content-assistant/plans/agent-that-learns-a-codebase.md.

## What's built

| piece | status |
|---|---|
| memory, anchors, refresh classifier, retrieval (`docs/design/memory-and-anchors.md`) | built (T7a) |
| agent contract: the `honeyguide` CLI, question inbox, page server, watcher (`docs/design/agent-contract.md`) | built (T7.1) |
| plugin: the Guide skill and four subagents (`skills/`, `agents/`) | written (T7.2), not yet run end to end |
| the map page | step 3 (T7.3); `serve` shows a placeholder until then |
| flow swimlane diagrams and the module graph | step 4 (T7.4) |
| refresh applied to saved memory | step 5 (T7.5); `refresh-plan` is a dry run until then |
| runtime confirmation of flow hops in the product | not built; the trace script in `eval/trace/` is the eval's |

## Install

1. The CLI, on your PATH (standard library only, Python 3.10+):

   ```bash
   uv tool install --editable ~/Documents/GitHub/honeyguide
   honeyguide --help
   ```

   Without it, the skill falls back to `uv run --quiet --project <plugin dir> honeyguide`.

2. The plugin. This repo is its own marketplace (`.claude-plugin/marketplace.json`). In Claude Code:

   ```
   /plugin marketplace add ~/Documents/GitHub/honeyguide
   /plugin install honeyguide@honeyguide
   ```

   or add it to `~/.claude/settings.json` the way the research plugin is added:

   ```json
   "extraKnownMarketplaces": {"honeyguide": {"source": {"source": "directory",
                              "path": "/Users/<you>/Documents/GitHub/honeyguide"}}},
   "enabledPlugins": {"honeyguide@honeyguide": true}
   ```

3. Optional, to skip permission prompts: allow `Bash(honeyguide:*)` in the target repo's settings.

## Use

In a Claude Code session inside the repo you want to learn (plugin skills are namespaced, so the command is
`/honeyguide:honeyguide`; below, `/honeyguide` for short):

- `/honeyguide explore`: the Cartographer maps the repo (Overview, Modules, Flows; every sentence a claim
  citing its lines), then the Checker re-reads each claim against those lines.
- `/honeyguide open`: serves the map on `127.0.0.1:8780`, opens it, and starts the watcher. Highlight
  anything and ask; the question goes to this session, an Investigator (or the Tracer, for "what happens
  when ..." questions) answers, and the answer appears beside your highlight. The page never starts Claude.
- `/honeyguide refresh`: after the code changes, shows what happened to each saved claim.

Memory lives in `~/.honeyguide/<repo id>/` (or `$HONEYGUIDE_HOME`), never in the checkout.
`honeyguide status`, `honeyguide export` and `honeyguide import` inspect and move it.

## Folders

`.claude-plugin/`, `skills/`, `agents/` (the plugin), `src/honeyguide/` (the CLI and page server),
`docs/design/` (data model and contract), `mockup/` (static UX mockup), `eval/` (isolation pilot, runtime
traces, questions, later the eval), `outputs/` (captures), `tests/`. Target repos (nanochat, waku-agent) are
cloned outside this repo, in `~/Documents/GitHub/honeyguide-targets/`.
