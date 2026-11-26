# Animation Studio: handoff and roadmap (written 2026-11-21)

> **REMOVED FROM THE APP on 2026-11-26 (user's decision).** The Animation feature (`#/anim`, Toon Studio, Motion Graphics, Blender episodes,
> Post kit) is no longer part of Drama Recap Studio. Its code was moved, not deleted, to `_backup/animation-removed-2026-11-26/`
> (`animation.py`, `anim_ai.py`, `motion.py`, `blender_fix.py`, `post_kit.py`, `engine_health.py`, `web/toon.js`, their three test files, and the
> pre-removal copies of `server.py`, `web/index.html`, `providers.py`, `i18n_en.json`). Everything below is kept only as a record; do not
> continue it in this repo unless the user asks to bring Animation back. The Dubbing page replaced it: see `docs/dubbing-handoff.md`.

Read this first if you are a new Claude Code session (any account) continuing the Animation work. The user writes in **Burmese**:
reply in Burmese, keep code/comments in English. Nothing from this work is committed yet (see "State").

> Resume prompt to paste: *"Read docs/animation-studio-handoff.md and continue with the next item in 'Order of work'. Do not start anything
> that is marked as waiting for my decision."*

## 1. What exists (the product)

An Animation workspace inside the desktop app (`#/anim`, "Toon Studio"): idea / script -> voice -> storyboard -> render -> post kit.

| Area | Status |
|---|---|
| Toon Studio UI (Home, Series, Blender, Library, Exports, Render Queue), wizard (Idea > Script > Storyboard > Voice > Render), One shot vs multi-part series with story memory | works |
| **Motion Graphics Explainer** (Remotion + a fixed component library; AI writes a scene *plan* JSON, stills, AI review, "Fix with AI", manual tweak, final MP4) | works end to end |
| **Cartoon 3D** (Remotion + three.js, Claude writes scene code) | compiles and renders, but the result from scratch is **weak** (character half out of frame); "Fix with AI" (edit code from a still + feedback) works |
| **Blender episodes** (`big-body-short` pipeline): browse shots, chat-fix a shot, re-render still/clip, rebuild voice, assemble, quality gate, undo, render missing | works; the two episodes were built **by hand**, the app cannot create a Blender episode from a topic yet |
| **Post kit** (3 thumbnails with hook text, Burmese + English caption, titles, hashtags) | works (tested on Blender episodes only) |
| Provider chain for every AI step: Claude (official or relay) > Gemini > OpenAI > OpenRouter > Codex CLI > Claude Code CLI > local gemma | Claude relay, Gemini, local tested; OpenAI/Codex/Claude Code CLI **not tested**; OpenRouter key is valid but has no credit (402) |
| Settings > Cloud / API Key: show/hide, Test the typed value without saving, optional Claude base URL (relay) | works |
| Other styles (3D Explainer/ZackDFilm, Rick clip, Block World/Roblox, Stickman, Cinematic, Custom) | **brief only**: "Render" saves a brief, no engine |

## 2. State of the repo

**Not committed.** `git status` shows ~26 changed/new paths. New files: `src/recap_engine/{motion,blender_fix,post_kit}.py`,
`src/recap_engine/web/toon.js`, `skills/` (copies of the Blender/Remotion skills + `zackd-blender`), `tests/recap/test_toon_engines.py`,
`docs/animation-studio-handoff.md`. Modified: `server.py`, `animation.py`, `anim_ai.py`, `cloud.py`, `desktop.py`, `web/index.html`, `tests/recap/conftest.py`.
Ask the user before committing. Open question: whether `skills/` should be committed (it is 4+ MB and partly private study material; the
reference frames were deliberately NOT copied).

## 3. How to run

```powershell
.venv-recap\Scripts\pythonw.exe -m recap_engine.desktop       # the app (port 8765; restart it to load new code)
.venv-recap\Scripts\python.exe -m pytest tests/recap -q       # 49 tests, all pass, no network needed
```
- Use the `.venv-recap` python for anything in `src/recap_engine`. For the Blender episode tools use
  `Desktop\Code Claude\roblox-shorts\.venv\Scripts\python.exe` (has edge_tts/numpy). Never call bare `python` for those (Windows Store stub).
- Blender: `C:\Program Files\Blender Foundation\Blender 5.3\blender.exe` (override with env `BLENDER_EXE`). Git Bash `sh` is used for
  `assemble.sh` / `render_all.sh` (`C:\Program Files\Git\bin\sh.exe`). `ffmpeg` must be on PATH.
- Keys live only in `config/api_keys.json` (git-ignored, local). **Never write a key into the repo, a doc or a test.** The user pasted a relay
  key in chat once; tell them to revoke it and make a new one.
- Claude relay: Settings > Claude API key + "Base URL" (`https://api.miraiapi.com` was used). Model names are mapped (`claude-opus-5-5` ->
  `claude-opus-4.8`, `claude-sonnet-5-5` -> `claude-sonnet-5`). Everything the app sends to Claude then goes to that third party: say so.
- Do **not** run the relay's "install" PowerShell script from the user's paste (it rewrites `~/.claude/settings.json` and runs a remote script).
  The user ran it by mistake once; a backup is at `~/.claude/settings.json.mirai-backup-*`.

## 4. Where things are

Repo (`C:\Users\Zayar Myo Oo\Desktop\aivoiceclone`):
- `src/recap_engine/web/toon.js`: whole Toon Studio UI (wizard, editors, Blender tab, Post kit). Routes `#/anim/<home|series|blender|library|exports|queue|new|p-<id>>`.
- `src/recap_engine/motion.py`: Motion Graphics engine + **`_call()` = the provider chain used by every AI step** (Gemini/OpenAI/OpenRouter/CLI helpers live here).
- `src/recap_engine/anim_ai.py`: Cartoon 3D code writing (`generate`, `revise_code`), Claude client, relay-safe `_ask` (one file per reply, empty-stream retry).
- `src/recap_engine/animation.py`: task runner for the Remotion project (`voice`, `ai_code`, `ai_fix`, `mg_*`, `render`, `mux`), `entry()` makes a per-short Remotion entry.
- `src/recap_engine/blender_fix.py`: Blender episode tools + chat-fix (edits only `def sN()` in `render_shot.py`, rolls back on failure).
- `src/recap_engine/post_kit.py`: thumbnails/caption/hashtags.
- `src/recap_engine/cloud.py`: keys, relay, key Test. Server endpoints: `/api/toon`, `/api/anim/*`, `/api/mg/*`, `/api/bl/*`, `/api/kit/*`.
- `skills/`: Blender + Remotion skills, `zackd-blender` (ZackDFilm workflow adapted to Blender), `references/stickman_explainer_style.md`.

Outside the repo (`C:\Users\Zayar Myo Oo\Desktop\Code Claude`, **not under git**):
- `my-first-short/`: Remotion project. `src/videos/mg/MotionExplainer.tsx` (Motion Graphics library), `src/MgRoot.tsx` + `scripts/mg.mjs`
  (fast stills/render, `public_mg/`), `src/videos/survivaltips/` is a **half-made short of the user's** (voice shorter than its story): do not delete without asking.
- `big-body-short/`: Blender pipeline. `lib/`, `episodes/paradox` (THE SANDWICH PARADOX, 2:44, card style), `episodes/pagoda`
  (WHY PAGODAS SURVIVE EARTHQUAKES, 58.9 s, stickman-3D look; `env.py` = sky/grass/mountains/pagoda/cutaway/VFX), `episodes/ep1..ep3(_mm)` (the user's series).
- `kenney_*` asset kits, `roblox-shorts` (venv with edge_tts).

## 5. Roadmap (the user's list) with real status

Legend: done / partial / missing. "T-free" = needs no AI tokens.

**Phase 1 Core engine** (all missing, all T-free): Blender auto-detection, engine health check, GPU detection (EEVEE is used, so OptiX is
irrelevant: just check GPU + EEVEE renders a frame), dependency checker (FFmpeg/Blender/Python/venvs), error log page.

**Phase 2 AI production:** Story Director **missing**, Automatic Shot Planner **missing**, Automatic Scene Builder **missing** (these three
are the real product gap: today a human/Claude hand-writes `shots.py` + `render_shot.py`). Character Lock done (`assets/registry.json`),
Reusable Asset Library partial (registry + `env.py`; needs a library API), Motion Library partial (walk/sit/doze/lie_down), Camera
Director and Lighting Director done (skill `lib/`).

**Phase 3 Audio and editing:** Burmese TTS partial (app has Edge/Gemini voices; not wired into Blender episodes), Lip sync partial (mouth open/close from
audio level, not phonemes), Auto SFX done (synth library), Multi-track done (voice/music/sfx stems), Auto captions done (word by word).

**Phase 4 Render and recovery:** Draft preview done (stills), Render queue partial (jobs exist, UI is basic), Checkpoint/resume done
(`render_all.sh` skips finished shots), Shot regeneration done, Autosave/Version history partial (`render_shot.bak_*.py`, undo button; no history UI).

**Phase 5 AI quality control:** Consistency check done, Scene validation partial, Animation review done (qa_critic proxies + human review page), Audio sync
check done, AI auto-repair partial (chat-fix per shot; no automatic loop).

**Phase 6 Final export:** 9:16 only (16:9 and 1:1 presets **missing**), quality presets missing, Local/Cloud AI modes done, Project backup missing.

## 6. Order of work agreed with the user

1. **Phase 1** (token-free, fast). 2. Token-free gaps of Phase 4/6 (version history, project backup, 16:9/1:1 export, render queue UI).
3. **Phase 2 core** (Story Director + Shot Planner + Scene Builder), the main product, spends tokens: do it after 1 and 2.
4. Phase 5 auto-repair loop. 5. Remaining style engines (ZackDFilm, Rick clip, Block World, Stickman, Cinematic) as "style packs" on top of 3.
The user asked specifically: **do the token-free items first.**

## 7. Known problems (be honest about them)

- The look of the Blender stickman-3D explainer is ~60-70 % of the user's reference videos (needs more realistic grass/sky/volumetrics, more VFX,
  more environments: field, canyon + rails, castle, workshop, richer mechanism cutaways). Reference files are private study material: never copy their
  scripts/characters, never publish them.
- Cartoon 3D from scratch is low quality; consider routing it through the Blender pipeline instead.
- Without a key the local model can write a wrong number into a Motion Graphics plan (it showed 100 % for a 10 % script). Warn in the UI or verify numbers.
- The Claude relay sometimes returns an empty stream and drops responses longer than ~5 min (both handled by retry / one file per reply).
- Untested: Codex CLI, Claude Code CLI, OpenAI provider; Burmese thumbnail titles; Post kit for Motion/Cartoon.
- Facts in the generated explainers (e.g. "1,400 years", "over a thousand quakes a year") come from the model and are **not verified**: the user must check before publishing.
- Edge TTS sometimes returns no audio for fast requests (retry with delay is in `gen_vo.py`); `en-US-AndrewNeural` failed on long lines, use Ryan/Thomas/Brian.

## 8. Decisions still waiting for the user

1. Which style to finish first (recommendation: the Blender stickman-explainer).
2. Video language: English (like the references) or Burmese (their audience).
3. Keep using the third-party Claude relay, or only the user's own keys.
4. Confirm: reference-quality = **own** characters and scripts in a similar quality level, never copies.
5. Whether to commit, and whether `skills/` goes into git.

## 9. Lessons that cost time (do not repeat)

- Look at stills first (`board.sh`), render clips only after the board is right; fix only flagged shots; max 3 QA rounds then ask the user.
- 9:16 two-shots need distance in proportion to the gap and lens <= 28 or people are cropped. Rigs look objects up **by name**: copies of a character need unique names.
- In this EEVEE, world volume fog renders black: use `look.fog_box()`. Colour management: set AgX before judging colours.
- Shell quirk in this environment: backslash escapes inside Python source written through a shell heredoc get eaten. Write files with the editor tool, then run them.
- Windows: `sleep` in the shell is blocked; wait with a polling `until` loop. Process substitution (`<(...)`) does not work with Windows ffmpeg.
- Tests must never read the developer's real `config/api_keys.json` (an autouse fixture in `tests/recap/conftest.py` isolates it).
