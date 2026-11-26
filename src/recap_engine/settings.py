"""Project settings (all optional; defaults give the one-click first draft)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["recap", "pro", "subtitle"]  # subtitle: original audio + Burmese subs only
Aspect = Literal["9:16", "16:9", "1:1", "4:5"]

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


class CaptionStyle(BaseModel):
    font: str = "Noto Sans Myanmar"
    size: int = Field(64, ge=20, le=160)  # px at 1080 width
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline: float = 4.0
    shadow: float = 1.5
    box: bool = False
    box_color: str = "#000000AA"
    # auto: on top of the burned-in subtitle band the OCR stage found (bottom when there is none)
    position: Literal["bottom", "middle", "top", "custom", "auto"] = "bottom"
    pos_pct: float = Field(0.86, ge=0.05, le=0.98)  # custom: vertical centre as fraction of height
    width_pct: float = Field(1.0, ge=0.3, le=1.0)  # caption width; 1.0 = auto safe margins
    bold: bool = True
    burn: bool = True  # False: no burned captions (SRT still exported)
    margin_v_pct: float = 0.14  # distance from edge, fraction of height
    keyword_color: str = "#FFD400"
    keywords: list[str] = []
    karaoke: bool = False
    max_chars_per_line: int = 22



Rights = Literal["user_owned", "licensed", "permission_unknown", "requires_review"]
TfPreset = Literal["clean_drama", "cinematic_drama", "vertical_recap", "subtitle_focus", "custom"]
ColorPreset = Literal["natural", "cinematic", "warm_romance", "dark_thriller", "clean_social"]


class ColorSettings(BaseModel):
    preset: ColorPreset = "natural"
    brightness: float = Field(0.0, ge=-0.3, le=0.3)
    contrast: float = Field(1.0, ge=0.7, le=1.4)
    saturation: float = Field(1.0, ge=0.5, le=1.6)
    gamma: float = Field(1.0, ge=0.7, le=1.4)
    sharpness: float = Field(0.0, ge=0.0, le=1.5)  # unsharp amount
    temperature: int = Field(6500, ge=3000, le=10000)  # Kelvin; 6500 = neutral
    denoise: float = Field(0.0, ge=0.0, le=6.0)  # hqdn3d strength
    shadows: float = Field(0.0, ge=-0.2, le=0.2)  # lift(+)/crush(-)
    highlights: float = Field(0.0, ge=-0.2, le=0.2)  # recover(-)/boost(+)


class WatermarkSettings(BaseModel):
    text: str = ""  # channel name / text watermark (user-owned branding only)
    logo_path: str | None = None  # PNG/JPG/WebP (SVG rasterised if ffmpeg supports it)
    position: Literal["top_left", "top_right", "bottom_left", "bottom_right", "center"] = "top_right"
    size_pct: float = Field(0.14, ge=0.03, le=0.5)  # logo width as fraction of video width
    opacity: float = Field(0.8, ge=0.05, le=1.0)
    margin_pct: float = Field(0.04, ge=0.0, le=0.2)
    animated: bool = False  # gentle fade in/out every 20 s
    motion: Literal["fixed", "fade", "move"] = "fixed"  # move: jumps to a new spot every few seconds


class TransformSettings(BaseModel):
    """Advanced Video Transformation. enabled=False -> pipeline output is byte-for-byte unchanged."""
    enabled: bool = False
    preset: TfPreset = "custom"
    smart_reframe: bool = False  # face-tracking crop (falls back to settings.reframe)
    subtitle_blur: bool = True  # blur the detected Chinese subtitle band only
    blur_strength: float = Field(1.0, ge=0.2, le=2.0)
    subtitle_background: Literal["none", "frosted", "box"] = "none"
    background_opacity: float = Field(0.45, ge=0.0, le=1.0)
    subtitle_replace: bool = True  # burn Burmese subs (False: soft SRT only)
    avoid_faces: bool = True  # move Burmese subs to top when a face sits in the subtitle band
    watermark: bool = False
    wm: WatermarkSettings = WatermarkSettings()
    border: Literal["none", "line", "glow", "line_glow"] = "none"  # frame decoration
    border_color: str = "#FFFFFF"
    glow_colors: list[str] = ["#FF3B5C", "#3B7BFF"]  # left / right edge light
    color: bool = False
    col: ColorSettings = ColorSettings()
    upscale: bool = False  # lanczos when source is smaller than output
    stabilize: bool = False
    audio_enhance: bool = False  # voice clarity / noise reduction / limiter
    loudnorm: bool = True
    scene_chapters: bool = False
    verify: bool = True
    codec: Literal["h264", "h265"] = "h264"
    resolution: Literal["1080", "720", "original"] = "1080"
    fps: int = Field(30, ge=15, le=60)
    quality: int = Field(21, ge=14, le=35)  # CQ/CRF, lower = better
    bitrate_k: int | None = None  # set -> VBR target instead of CQ
    aspect_original: bool = False  # keep the source aspect ratio


class RightsInfo(BaseModel):
    status: Rights = "permission_unknown"
    owner: str = ""
    source_url: str = ""
    attribution: str = ""
    license_note: str = ""
    permission_doc: str | None = None  # path to licence / permission file


class ProjectSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)  # keeps types stable -> stable cache hashes

    mode: Mode = "recap"
    language: Literal["my", "en", "th"] = "my"
    target_seconds: float = Field(180, ge=15, le=1800)
    aspect: Aspect = "9:16"
    height: int = 1920  # derived from aspect when rendering; proxy uses smaller
    voice_id: str = "male_calm"
    narration_style: Literal["storyteller", "calm", "suspense", "energetic", "documentary"] = "storyteller"
    # how the script talks: normal, rude (crude street-talk commentary with swearing) or funny (jokes and exaggeration);
    # the story facts stay the same in all three
    tone: Literal["normal", "rude", "funny"] = "normal"
    # Recap: open with a teaser intro written from the WHOLE story (why it is worth watching, no spoilers)
    # over a fast montage of its key moments, then the normal recap. Made for narration-only videos.
    hook_intro: bool = False
    intro_seconds: float = Field(12, ge=6, le=30)
    caption: CaptionStyle = CaptionStyle()
    mirror: bool = False
    zoom: float = Field(1.0, ge=1.0, le=1.3)
    reframe: Literal["center_crop", "blur_fill"] = "blur_fill"
    original_audio: Literal["remove_vocals", "keep_all", "mute_all"] = "remove_vocals"
    hardsub: Literal["blur", "box", "crop", "keep"] = "blur"
    bgm_path: str | None = None
    whisper_model: str = "large-v3-turbo"  # tested best: clean sentence segments; "belle-zh" garbles + merges lines
    llm_model: str = "gemma4:26b"  # best Burmese; "gemma4:12b" balanced, "gemma4:e4b" fastest
    vision_model: str | None = None  # e.g. "qwen2.5vl:3b"; None -> auto-detect, skip if absent
    use_ocr: bool = True
    proxy: bool = False  # low-res preview render
    hook_index: int = 0  # which of the 3 hooks is used for beat 0
    transform: TransformSettings = TransformSettings()
    # studio editor: user-drawn regions in SOURCE coords (0..1); blur only inside each box
    blur_boxes: list[dict] = []  # {x0,y0,x1,y1,strength(1..40)}
    crop_box: dict | None = None  # {x0,y0,x1,y1}: area of the source to keep
    voice_speed: float = Field(1.0, ge=0.6, le=1.6)
    tighten_gaps: bool = False  # pro/subtitle: cut silent stretches between lines (shorter video)
    max_gap: float = Field(2.0, ge=0.1, le=8.0)  # silence longer than this is cut (2 s keeps action beats)
    post_kit: bool = True
    hashtags: str = ""  # always-added hashtags
    add_fyp: bool = True
    rights: RightsInfo = RightsInfo()
