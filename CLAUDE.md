# Project notes for Claude Code

- The user writes in Burmese: answer in Burmese, keep code and comments in English. Be honest about what is tested and what is not.
- **Dubbing work (`#/dub`: English short -> Burmese voice + Burmese captions): read `docs/dubbing-handoff.md` first.**
- Animation (Toon Studio, Motion Graphics, Blender episodes, Post kit) was removed from this app on 2026-11-26. Its code is parked in the
  git-ignored `_backup/animation-removed-2026-11-26/`; `docs/animation-studio-handoff.md` is only a record. Do not rebuild it unless asked.
- Work is split into one session per task: lanes, rules and paste-ready prompts are in `docs/sessions.md`.
- Never put API keys in the repo (keys live in the git-ignored `config/api_keys.json`). Do not commit unless the user asks.
- Run tests with `.venv-recap\Scripts\python.exe -m pytest tests/recap -q` (all must pass).
