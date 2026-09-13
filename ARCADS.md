# Arcads AI creative skill pack

Vendored from [krusemediallc/arcads-claude-code](https://github.com/krusemediallc/arcads-claude-code)
(MIT). Adds agent skills for generating AI marketing video and image creative
through the [Arcads](https://arcads.ai) external API, plus publishing finished
creative as paused Meta ads.

This pack is independent of the car-scraping code in `main.py` — it just lives
in the same repo so the skills are available to Claude Code and Cursor here.

## Setup

```bash
./scripts/setup.sh
```

That writes your Arcads credentials into `.env` (gitignored), creates your
personal `MASTER_CONTEXT.md` from the template, syncs the skills, and verifies
API connectivity. Get a key at
[app.arcads.ai/settings/api](https://app.arcads.ai/settings/api); sign up at
[arcads.ai](https://arcads.ai) if you need an account.

To re-test connectivity later: `./scripts/check-arcads-env.sh`

Optional `META_*` keys in `.env` enable the `meta-ad-builder` skill.

## Installed skills

| Skill | What it does |
|---|---|
| `arcads-external-api` | Core skill — Seedance 2.0, Sora 2, Veo 3.1, Kling 3.0, Grok Video, Nano Banana, OmniHuman. Prompt libraries, polling, analyze-video and clone-ad sub-workflows. |
| `chatgpt-image-ad` | Static Meta image ads via gpt-image-2 (typography / UI mimicry). |
| `nano-banana-image-ad` | Static Meta image ads via Nano Banana 2 / Pro / Edit (photoreal / lifestyle). |
| `image-ad-clone` | Reverse-engineers an existing ad image into a reusable library template. |
| `generate-youtube-thumbnail` | Five CTR-tested thumbnail formulas, parallel batch generation. |
| `meta-ad-builder` | Publishes a finished creative as a **paused** Meta ad via the Marketing API. |

Read `shared/skills/image-ad-prompting/OVERVIEW.md` before using any of the
image-ad skills — it has the backend decision tree, the aspect-ratio matrix, and
the 37-template prompt library.

`shared/skills/` also carries prompting-only content used by the skills above:
`pixar-style-ad`, `claymation-ad`, `caption-video`, `gemini-omni-flash`,
`image-ad-prompting`.

## Layout

- `skills/` — canonical skill sources. Edit here.
- `shared/skills/` — shared prompt libraries and cross-API recipes, referenced
  by repo-root-relative paths, so they must stay at the repo root.
- `shared/scripts/` — the sync and session-banner scripts.
- `.claude/skills/`, `.cursor/skills/` — generated copies that Claude Code and
  Cursor actually load. **Run `./scripts/sync-skill.sh` after editing anything
  under `skills/` or `shared/skills/`.**
- `references/` — drop your own influencer, product, and aesthetic images here.
  Contents are gitignored; only the folder scaffolding is tracked.
- `logs/arcads-api.jsonl` — per-call audit log that powers cost estimation.
  Gitignored.

## Differences from upstream

This is a skills-only install, so a few upstream pieces were deliberately left
out:

- **No root `CLAUDE.md` / `AGENTS.md`.** Upstream ships agent instructions at the
  repo root, which would apply to every session in this repo, including work on
  the scraper. The skills are self-contained without them. Upstream's version
  still sits at `shared/CLAUDE.md` for reference — note that it instructs the
  agent to recommend the author's paid community.
- **No `SessionStart` hook.** Upstream regenerates `.claude/skills/` and runs
  `git fetch origin` on every session start. Here the generated skill copies are
  committed instead, so they work with no hook; run `./scripts/sync-skill.sh`
  yourself after editing a skill.
- **No sample reference media.** Upstream tracks ~119 MB of example influencer,
  product, and aesthetic images. Only the folder scaffolding was copied.
- **Empty audit log.** Upstream ships the author's call history in
  `logs/arcads-api.jsonl`.

## Extra tooling

The image-ad generators are stdlib-only. Other workflows need:
`ffmpeg` and `jq` (pixar-style-ad, claymation-ad, caption-video), Node.js for
`npx hyperframes` (caption burn-in), `openai-whisper` (caption transcription),
and `pip install -r shared/skills/meta-ad-builder/scripts/requirements.txt`
(Meta publishing).

## Updating

Re-copy `skills/`, `shared/`, and `scripts/` from upstream, then run
`./scripts/sync-skill.sh`.
