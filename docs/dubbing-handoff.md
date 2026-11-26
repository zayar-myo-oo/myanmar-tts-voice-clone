# Dubbing: handoff (written 2026-11-26)

Read this first when continuing the Dubbing work. The user writes in Burmese: reply in Burmese, code and comments in English.
Nothing is committed (commit only when the user asks).

## What it is

A page in the desktop app (`#/dub`, sidebar icon where Animation used to be): give it a short vertical video with English narration and
burned-in English word-pop captions, get an MP4 with a Burmese voice, the English text covered and Burmese phrase-pop captions in the
same place.

| File | Role |
|---|---|
| `src/recap_engine/dubbing.py` | the whole pipeline + job runner (also a CLI: `python -m recap_engine.dubbing <video>`, `--job <id> --from <stage>`) |
| `src/recap_engine/dub_vox_worker.py` | runs inside the Voice Workbench venv, wraps its `engine.clone_burma_cat` (VoxCPM2) |
| `src/recap_engine/web/dub.js` | the page (list + new job, job page with player and line editor) |
| `src/recap_engine/server.py` | `/api/dub*` endpoints (bottom of the file) |
| `tests/recap/test_dubbing.py` | 18 tests of the parts that need no GPU / models |

Jobs live in `projects/_dub/<id>/` (git-ignored): `source.*`, `vocals.wav`, `bed.wav`, `transcript.json`, `captions.json`, `lines.json`,
`tts/`, `plan.json`, `captions.ass`, `final.mp4`, `final.srt`, `log.txt`. Each stage skips itself when its file exists, so delete a file
to force that stage again.

## Pipeline

1. **audio**: demucs two-stems -> `vocals.wav` (for ASR) + `bed.wav` (music / SFX, kept under the new voice).
2. **transcribe**: faster-whisper large-v3-turbo, English, word timestamps -> sentences (`build_sentences`).
3. **captions**: RapidOCR (local, CUDA). Pass 1 at 2 fps keeps only text that matches what is being said (so signs in the scene are not
   touched) and finds the caption band. Pass 2 at ~15 fps, detection only inside the band, records boxes per frame.
4. **translate**: the app's LLM (`llm.chat_json`; default local `gemma4:26b`, or the cloud model when the app is in cloud mode). One line per
   sentence, hook first line, syllable budget per line, a second pass shortens lines that are far over budget. Only text is sent to the LLM.
5. **voice**: `bc:<id>` voices = Burma Cat / VoxCPM2 through the Voice Workbench in `Desktop\voice model collection` (its GPU/Vulkan
   runtime is used when present); other ids go through `tts.synth_any` (Nara Mini, Microsoft, ...).
6. **render**: per sentence the voice is sped up at most 1.2x, then the picture of that sentence is slowed at most 1.35x (the bed audio is
   stretched the same way). Frames are read with OpenCV, text is removed (`remove_text`: glyph-mask inpaint, or a feathered blur box; auto
   picks blur when the background is too bright / busy), piped to ffmpeg, captions burned with libass (`shaping=complex`, Noto Sans Myanmar).

## Tested / not tested (2026-11-26)

- Tested end to end on two of the user's reference videos (Circle3D "Were Catapults Useless", Rick Clips "This Shape Saved Roller
  Coasters"): see the session report for the result of each. Burmese shaping was checked on real output frames (correct).
- The page was opened in the app's web UI: new-job form, job page with player and line editor render without console errors from dub.js.
- NOT tested: the Roblox style (captions at the top, two lines, 60 fps), videos without burned-in captions, cloud LLMs, Nara / Microsoft
  voices in a dub, the "Pro" VoxCPM2 preset in a full job, Cancel / Delete / edit-and-re-make buttons by hand, the packaged desktop window.
- Known weak points: `gemma4:26b` translation is understandable but not polished and sometimes ignores the length budget; the blur box is
  visible on busy backgrounds; the highlight colours a whole caption chunk, not a single word; a second app instance and a running job share
  the GPU without a queue between processes (inside one process jobs run one at a time).

## Added later the same day: hook choices, glossary, review gate

- **Review gate** (`review` option, on by default): the job stops in state `review` after translate; the page shows the lines and a
  "make the voice and the video" button (PUT `/api/dub/{id}` -> runs from `voice`). The CLI needs `--review false` to run straight through.
- **Hook choices**: a separate small LLM call writes 3 alternatives for line 1 (`lines.json: hooks`); the page shows them as buttons.
  Asking for them inside the main translation call made `gemma4:26b` return one keyword per line, so keep it separate.
  `looks_collapsed` detects that failure and retries the translation once.
- **Glossary**: `config/dub_glossary.json` (English term -> Burmese), edited on the Dubbing page (`/api/dub/glossary`). Only terms that occur
  in the narration are put in the prompt. The file is user data and is not git-ignored yet (decide with the user).
- Tested: unit tests, and one real run in the web UI (Catapults: glossary terms were used in every line, a hook was picked with the
  button, the voice + render button produced the video). Not tested: glossary with many entries, cloud LLMs.

## Next ideas (not started; ask the user which)

One voice per character, copy the original caption colours, LaMa inpainting, batch folder mode, post kit (titles / hashtags / thumbnail),
reuse the review gate + glossary for Drama Recap (Lane B).

## Rights

The reference videos in `Desktop\Ai Animation\...\Reference Video(s)` belong to other creators. They are local test input only: never copy
them or their dubs into the repo. The page shows a note that re-uploading a dub of someone else's video can raise copyright / reused-content
issues.

## Added 2026-11-26 (third round): tone for Recap + Dubbing, auto caption placement for Recap

- **Tone** (`normal` / `rude` / `funny`): `script.TONE_HINTS` + `script.tone_rule()`. Recap: `ProjectSettings.tone`, used in the recap
  narration prompt, its review pass (told to keep the narrator's remarks) and the dialogue translation prompt; part of the script cache key.
  Dubbing: `tone` option; changing it on a finished job re-translates (the old lines are kept as `lines.<tone>.json.bak`). UI: Studio ->
  Voice tab, and the Dubbing options. The rude tone uses Burmese swear words on purpose (the user asked for it, for fictional characters);
  the UI warns that platforms may restrict such videos. Story facts must stay the same in every tone.
- **Recap caption position "auto"** (`CaptionStyle.position`, new default in the UI, existing users are switched once): `captions.resolve_auto`
  is applied in `pipeline.Context.settings`, so every stage sees a concrete "custom" position on the OCR subtitle band plus one extra, wider
  auto blur box (`blur_boxes` item with `auto: True`). `captions.src_to_out_y` maps source height to output height (crop box, zoom, reframe;
  "original aspect" only when `transform.enabled`). No band found -> "bottom". The saved settings stay "auto".
- Tested on real video: one new Recap project from an old source (recap mode, rude tone: script swears and keeps the events; captions sit
  on the blurred band in the 9:16 blur-fill layout) and one funny-tone dub of Catapults. Unit tests in `tests/recap/test_auto_tone.py`.
- Not tested: transform render path (`transform.enabled`, the user's usual "original aspect" setup) with auto placement on a real video,
  subtitle / pro modes with a tone, funny tone in Recap, rude tone in Dubbing, the new UI controls by hand. The funny tone from
  `gemma4:26b` is mild; a two-line caption can stick out a little above the blurred band.
- Later the same day: auto placement was also run on a real video through the transform render path with the user's usual settings
  (subtitle mode, `transform.enabled` + original aspect, 1920x1080, funny tone): blur and captions land on the band. The auto blur box now
  starts 3.5% above the band so the first line of a two-line caption is covered too (that last tweak is unit-tested only).
