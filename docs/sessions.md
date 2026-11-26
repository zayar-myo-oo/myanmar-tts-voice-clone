# Session lanes: how to split work so context stays small (written 2026-11-26)

One session = one lane = one task. Start a fresh session for the next task instead of continuing a long one. Reply to the user in Burmese.

## Lanes

| Lane | Work | Main files | Status |
|---|---|---|---|
| **B. Drama Recap** | Review gate (pause after script) + Glossary + pronunciation dictionary UI | `server.py`, `settings.py`, `script.py`, `web/index.html` | ready |
| **D. Dubbing** | English short -> Burmese voice + captions (`#/dub`). Built 2026-11-26; next steps are in `docs/dubbing-handoff.md` | `dubbing.py`, `dub_vox_worker.py`, `web/dub.js`, `server.py` | first version works |

Animation (old lanes A and C: Toon Studio, Motion Graphics, Blender episodes, Post kit) was **removed from this app on 2026-11-26** at the
user's request. The code was moved, not deleted, to `_backup/animation-removed-2026-11-26/` (git-ignored). Do not continue those lanes here.

## Rules

1. **One code-writing session at a time** in this folder. B and D both edit `server.py`, and nothing is committed, so parallel writers can overwrite
   each other. Read-only questions can run in any session at any time.
2. Parallel sessions (separate git worktrees) become possible only after the current work is committed. A worktree does not contain uncommitted
   files. Commit only when the user asks.
3. Work that lives in another folder (`Desktop\Ai Animation\...`) keeps its own sessions there; it does not belong to this repo's sessions.
4. Do not read large files whole (`web/index.html`, `server.py`): search first, then read only the lines needed.
5. End a session when its task is done, or earlier if the context is getting full. Before ending, update the notes (below).

## Handoff notes

| Lane | Update at the end of a session |
|---|---|
| D | `docs/dubbing-handoff.md` |
| B | the `recap-roadmap` memory file, or a short `docs/recap-handoff.md` if another account has to continue |

Write only what the next session cannot learn from the code: what was finished, what was tested and what was not, the next step, open questions.

## Prompts to paste into a new session

**Start lane B**
```
docs/sessions.md ကိုဖတ်ပြီး Lane B (Review gate + Glossary) ကို လုပ်ပါ။ Commit မလုပ်ပါနဲ့။
```

**Continue lane D**
```
docs/sessions.md နဲ့ docs/dubbing-handoff.md ကိုဖတ်ပြီး Dubbing ကို ဆက်လုပ်ပါ။ Commit မလုပ်ပါနဲ့။
```

**End any session**
```
ဒီ session ကို သိမ်းပါ။ docs/sessions.md အတိုင်း handoff note ကို update လုပ်ပေးပါ (ပြီးတာ၊ စမ်းပြီး/မစမ်းရသေးတာ၊ နောက်တစ်ဆင့်)။
```
