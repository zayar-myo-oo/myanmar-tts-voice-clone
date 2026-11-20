"""Public engine API used by the web server, the desktop worker and the CLI."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from . import analyze, captions, export, importer, qc, render, rights, script, timeline, transcribe, tts
from .manifest import Project, default_projects_root
from .pipeline import Context, ProgressCb, Stage, VramMonitor, run_stages
from .settings import ProjectSettings

STAGES: list[Stage] = [
    Stage("import", "ဗီဒီယို ယူနေပါတယ်", importer.stage_import_inputs, importer.stage_import),
    Stage("audio", "အသံ ထုတ်နေပါတယ်", analyze.audio_inputs, analyze.stage_audio),
    Stage("separate", "မူရင်းပြောသံနဲ့ နောက်ခံတေး ခွဲနေပါတယ်", analyze.separate_inputs, analyze.stage_separate,
          enabled=lambda c: c.settings.original_audio == "remove_vocals"),
    Stage("shots", "Shot တွေ ခွဲနေပါတယ်", analyze.shots_inputs, analyze.stage_shots),
    Stage("ocr", "မူရင်း စာတန်းထိုး ဖတ်နေပါတယ်", analyze.ocr_inputs, analyze.stage_ocr),
    Stage("vision", "ပုံရိပ်တွေကို နားလည်အောင် ကြည့်နေပါတယ်", analyze.vision_inputs, analyze.stage_vision,
          enabled=lambda c: c.settings.mode == "recap"),  # Pro Dub / Subtitle don't pick shots
    Stage("transcribe", "စကားပြော နားထောင်နေပါတယ်", transcribe.transcribe_inputs, transcribe.stage_transcribe),
    Stage("script", "Script ရေးနေပါတယ်", script.script_inputs, script.stage_script),
    Stage("voice", "မြန်မာ အသံ ထုတ်နေပါတယ်", tts.voice_inputs, tts.stage_voice,
          enabled=lambda c: c.settings.mode != "subtitle"),
    Stage("timeline", "Clip နဲ့ အသံ ညှိနေပါတယ်", timeline.timeline_inputs, timeline.stage_timeline),
    Stage("captions", "စာတန်းထိုး လုပ်နေပါတယ်", captions.caption_inputs, captions.stage_captions),
    Stage("render", "ဗီဒီယို ထုတ်နေပါတယ်", render.render_inputs, render.stage_render),
    Stage("qc", "အရည်အသွေး စစ်နေပါတယ်", qc.qc_inputs, qc.stage_qc),
    Stage("rights", "မူပိုင်ခွင့် အန္တရာယ် စစ်နေပါတယ်", rights.rights_inputs, rights.stage_rights,
          enabled=lambda c: c.settings.transform.enabled),
    Stage("export", "Post Kit နဲ့ ဖိုင်တွေ ထုတ်နေပါတယ်", export.export_inputs, export.stage_export),
]


def create_project(*, url: str | None = None, file: str | Path | None = None, settings: ProjectSettings | None = None,
                   projects_root: Path | None = None, title: str = "", series_id: str | None = None,
                   cookies_browser: str | None = None) -> Project:
    if not url and not file:
        raise ValueError("url or file required")
    p = Project.create(settings, projects_root, title=title)
    p.manifest.source = {"url": url, "original_file": str(Path(file).resolve()) if file else None,
                         "series_id": series_id, "cookies_browser": cookies_browser}
    p.save()
    return p


def run_project(project: Project, progress_cb: ProgressCb | None = None, cancel_event: threading.Event | None = None,
                force: set[str] | None = None, until: str | None = None) -> Project:
    ctx = Context(project, progress_cb, cancel_event or threading.Event(), force=force or set())
    stages = STAGES if until is None else STAGES[: [s.name for s in STAGES].index(until) + 1]
    t0 = time.time()
    with VramMonitor() as vm:
        try:
            run_stages(ctx, stages)
        finally:
            project.reload()
            prev = project.manifest.source.get("vram_peak_mib") or 0
            project.manifest.source["vram_peak_mib"] = max(prev, vm.peak)
            project.manifest.source["vram_baseline_mib"] = vm.baseline
            project.manifest.source["last_run_seconds"] = round(time.time() - t0, 1)
            project.save()
            from .pipeline import STAGE_LOCKS
            with STAGE_LOCKS["voice"]:  # never close the shared TTS worker under another job
                tts.TTSClient.close()
    return project


# ------------------------------------------------------------------ editing
def edit_beat(project: Project, beat_id: int, *, narration: str | None = None, voice_id: str | None = None,
              source_ranges: list | None = None, pinned_clips: list[int] | None = None) -> None:
    """Change one beat. Downstream stages re-run, but per-beat TTS and per-clip renders are
    cached by content hash, so only this beat's audio/clips are actually regenerated."""
    beats = project.read_json("script/beats.json", [])
    b = next(x for x in beats if x["id"] == beat_id)
    if narration is not None:
        from .burmese import normalize
        b["narration"] = normalize(narration)
        if "burmese" in b:
            b["burmese"] = b["narration"]
    if voice_id is not None:
        b["voice_id"] = voice_id or None
    if source_ranges is not None:
        dur = float(project.manifest.source.get("probe", {}).get("duration") or 0)
        shots = project.read_json("analysis/shots.json", [])
        b["source_ranges"] = script.validate_ranges(source_ranges, dur, shots)
    if pinned_clips is not None:
        b["pinned_clips"] = pinned_clips
    project.write_json("script/beats.json", beats)


def set_hook(project: Project, index: int) -> None:
    project.manifest.settings.hook_index = index
    project.save()


def update_settings(project: Project, **changes) -> None:
    data = project.manifest.settings.model_dump()
    for k, v in changes.items():
        if k == "caption" and isinstance(v, dict):
            data["caption"].update(v)
        else:
            data[k] = v
    project.manifest.settings = ProjectSettings.model_validate(data)
    project.save()


def list_projects(root: Path | None = None) -> list[dict]:
    root = Path(root or default_projects_root())
    out = []
    for m in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            p = Project(m.parent)
            st = p.manifest.stages
            probe = p.manifest.source.get("probe") or {}
            final = p.path("export", "final.mp4")
            out.append({"project_id": p.manifest.project_id, "title": p.manifest.title, "created": p.manifest.created,
                        "mode": p.manifest.settings.mode, "status": overall_status(p),
                        "language": p.manifest.settings.language, "aspect": p.manifest.settings.aspect,
                        "duration": probe.get("duration"),
                        "mb": round(final.stat().st_size / 1e6, 1) if final.exists() else None,
                        "done": sum(1 for s in st.values() if s.status == "done"), "total": len(STAGES)})
        except Exception:  # noqa: BLE001
            continue
    return out


def overall_status(p: Project) -> str:
    st = p.manifest.stages
    if any(s.status == "failed" for s in st.values()):
        return "failed"
    if any(s.status == "cancelled" for s in st.values()):
        return "cancelled"
    if any(s.status == "running" for s in st.values()):
        return "running"
    if st.get("export") and st["export"].status == "done":
        return "done"
    return "pending"


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="recap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="create + run a project")
    n.add_argument("source", help="video file path or URL")
    n.add_argument("--mode", default="recap", choices=["recap", "pro", "subtitle"])
    n.add_argument("--audio", default="remove_vocals", choices=["remove_vocals", "keep_all", "mute_all"])
    n.add_argument("--seconds", type=float, default=180)
    n.add_argument("--aspect", default="9:16")
    n.add_argument("--voice", default="male_calm")
    n.add_argument("--whisper", default="large-v3-turbo")
    n.add_argument("--llm", default="gemma4:26b")
    n.add_argument("--mirror", action="store_true")
    n.add_argument("--zoom", type=float, default=1.0)
    n.add_argument("--proxy", action="store_true")
    n.add_argument("--transform", action="store_true", help="Advanced Video Transformation ON")
    n.add_argument("--preset", default="custom",
                   choices=["clean_drama", "cinematic_drama", "vertical_recap", "subtitle_focus", "custom"])
    n.add_argument("--tf", default="{}", help='extra TransformSettings as JSON, e.g. {"smart_reframe":true}')
    n.add_argument("--rights", default="permission_unknown",
                   choices=["user_owned", "licensed", "permission_unknown", "requires_review"])
    n.add_argument("--owner", default="")
    n.add_argument("--until")
    n.add_argument("--projects", type=Path)
    r = sub.add_parser("run", help="resume / re-run a project")
    r.add_argument("project", type=Path)
    r.add_argument("--force", nargs="*", default=[])
    r.add_argument("--until")
    sub.add_parser("list")
    args = ap.parse_args(argv)

    def cb(e: dict) -> None:
        if e["message"]:
            print(f"{e['progress'] * 100:5.1f}% [{e['stage']}] {e['message']}", flush=True)

    if args.cmd == "list":
        print(json.dumps(list_projects(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "new":
        is_url = args.source.startswith(("http://", "https://"))
        s = ProjectSettings(mode=args.mode, target_seconds=args.seconds, aspect=args.aspect, voice_id=args.voice,
                            whisper_model=args.whisper, llm_model=args.llm, mirror=args.mirror, zoom=args.zoom, original_audio="keep_all" if args.mode == "subtitle" else args.audio,
                            proxy=args.proxy,
                            transform={**json.loads(args.tf), "enabled": args.transform, "preset": args.preset},
                            rights={"status": args.rights, "owner": args.owner})
        p = create_project(url=args.source if is_url else None, file=None if is_url else args.source, settings=s,
                           projects_root=args.projects)
        print("project:", p.root)
        run_project(p, cb, until=args.until)
    else:
        p = Project(args.project)
        run_project(p, cb, force=set(args.force), until=args.until)
    print("done:", p.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
