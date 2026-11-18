"""Rights Analysis (runs only with transform.enabled). Local, advisory only.

It records attribution / permission info and flags risk. It never labels output
"copyright-free" and makes no promise about platform claims (Content ID etc.)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .pipeline import Context

DISCLAIMER_MY = ("ဗီဒီယိုကို ပြင်ဆင်ထားတာ (crop, blur, color, logo) ဟာ မူပိုင်ခွင့်ကို မဖယ်ရှားပါ။ "
                 "Copyright claim မလာဘူးလို့ အာမမခံနိုင်ပါ။ ပိုင်ရှင်ရဲ့ ခွင့်ပြုချက် ရှိမှသာ တင်ပါ။")
STATUS_MY = {"user_owned": "ကိုယ်ပိုင်", "licensed": "လိုင်စင်ရှိ", "permission_unknown": "ခွင့်ပြုချက် မသိရ",
             "requires_review": "ပြန်စစ်ရန် လိုအပ်"}


def _union(iv: list[tuple[float, float]]) -> float:
    tot, end = 0.0, -1.0
    for a, b in sorted(iv):
        if b <= end:
            continue
        tot += b - max(a, end)
        end = b
    return tot


def footage_usage(timeline: list[dict], source_dur: float) -> dict:
    clips = [c for seg in timeline for c in seg["clips"]]
    out_dur = max((c["out_end"] for c in clips), default=0.0)
    used = _union([(c["src_start"], c["src_end"]) for c in clips])
    return {"source_seconds_used": round(used, 1), "source_duration": round(source_dur, 1),
            "pct_of_source_used": round(100 * used / max(1e-6, source_dur), 1),
            "pct_of_output_from_source": round(100 * sum(c["src_end"] - c["src_start"] for c in clips)
                                               / max(1e-6, out_dur), 1)}


def detect_static_marks(src: Path, n: int = 24) -> list[str]:
    """Corners with static, edge-rich pixels across many frames -> likely a channel logo / watermark."""
    import cv2
    cap = cv2.VideoCapture(str(src))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames = []
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / n))
        ok, f = cap.read()
        if ok:
            g = cv2.cvtColor(cv2.resize(f, (640, int(f.shape[0] * 640 / f.shape[1]))), cv2.COLOR_BGR2GRAY)
            frames.append(g)
    cap.release()
    if len(frames) < 6:
        return []
    st = np.stack(frames).astype(np.float32)
    std = st.std(axis=0)
    edges = np.mean([cv2.Canny(f, 80, 160) > 0 for f in frames], axis=0)
    h, w = std.shape
    ch, cw = int(h * 0.16), int(w * 0.22)
    corners = {"top_left": (slice(0, ch), slice(0, cw)), "top_right": (slice(0, ch), slice(w - cw, w)),
               "bottom_left": (slice(h - ch, h), slice(0, cw)), "bottom_right": (slice(h - ch, h), slice(w - cw, w))}
    found = []
    for name, (ys, xs) in corners.items():
        static_edges = (std[ys, xs] < 8) & (edges[ys, xs] > 0.8)
        if static_edges.mean() > 0.004:
            found.append(name)
    return found


def rights_inputs(ctx: Context) -> Any:
    return {"r": ctx.settings.rights.model_dump(), "render": ctx.project.stage("render").input_hash, "v": 1}


def stage_rights(ctx: Context) -> dict[str, str]:
    p = ctx.project
    r = ctx.settings.rights
    src_info = p.manifest.source
    usage = footage_usage(p.read_json("render/timeline.json", []), float(src_info.get("probe", {}).get("duration") or 0))
    ctx.progress(0.3, "Logo / watermark ရှိမရှိ စစ်နေပါတယ်")
    marks = detect_static_marks(p.source_video)
    doc_ok = bool(r.permission_doc and Path(r.permission_doc).exists())
    from_url = bool(src_info.get("url"))
    flags: list[str] = []
    status = r.status
    if status == "permission_unknown":
        flags.append("မူရင်း ဗီဒီယိုရဲ့ ပိုင်ရှင်/ခွင့်ပြုချက် အချက်အလက် မရှိသေးပါ။")
    if status == "licensed" and not doc_ok:
        flags.append("License ရှိတယ်လို့ ရွေးထားပေမဲ့ ခွင့်ပြုချက် စာရွက် (permission_doc) မတွဲထားပါ။")
        status = "requires_review"
    if status == "user_owned" and from_url:
        flags.append("ကိုယ်ပိုင်လို့ ရွေးထားပေမဲ့ ဗီဒီယိုကို URL ကနေ ဒေါင်းထားပါတယ်။ ပိုင်ရှင် ဟုတ်မဟုတ် ပြန်စစ်ပါ။")
        status = "requires_review"
    if status not in ("user_owned", "licensed") and usage["pct_of_output_from_source"] >= 50:
        flags.append(f"Output ဗီဒီယိုရဲ့ {usage['pct_of_output_from_source']}% က တခြားသူ့ footage ဖြစ်ပါတယ်။")
    if marks:
        flags.append("မူရင်းမှာ logo/watermark ဖြစ်နိုင်တာ တွေ့ပါတယ်: " + ", ".join(marks) +
                     "။ ဒါက ပိုင်ရှင်ရှိကြောင်း လက္ခဏာပါ (ဖျောက်မပစ်ပါနဲ့)။")
    if not (r.owner or r.attribution):
        flags.append("Credit / attribution မထည့်ရသေးပါ။")
    if flags and status == "user_owned":
        status = "requires_review"
    report = {
        "status": status, "status_my": STATUS_MY[status], "declared_status": r.status,
        "owner": r.owner, "source_url": r.source_url or src_info.get("url", ""), "attribution": r.attribution,
        "license_note": r.license_note, "permission_doc": r.permission_doc, "permission_doc_found": doc_ok,
        "footage": usage, "possible_third_party_marks": marks, "flags_my": flags,
        "checklist_my": [
            "မူရင်း ဗီဒီယို ပိုင်ရှင်ကို သိပြီလား။",
            "ပြန်တင်ခွင့် / ဘာသာပြန်ခွင့် စာနဲ့ ရထားပြီလား။",
            "Credit (မူရင်း ဇာတ်ကား/ချန်နယ် နာမည်) ထည့်ထားပြီလား။",
            "သုံးထားတဲ့ logo, font, နောက်ခံတေးဂီတ အားလုံး ကိုယ်ပိုင် သို့မဟုတ် ခွင့်ပြုချက်ရှိလား။",
            "Platform ရဲ့ မူပိုင်ခွင့် စည်းမျဉ်းကို ဖတ်ပြီးပြီလား။",
        ],
        "disclaimer_my": DISCLAIMER_MY,
    }
    p.write_json("export/rights_report.json", report)
    return {"rights": "export/rights_report.json"}
