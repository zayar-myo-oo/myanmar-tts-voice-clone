// Preview mode: a fake engine used when the UI runs in a normal browser (no Tauri runtime).
// It lets the interface be designed and reviewed without the Python worker. Audio is a
// short generated tone, clearly not speech.
import type { ExportResult, JobInfo, McpHttpStatus, McpStatus, ReviewItem, StudioClient, VoiceSummary } from "./types";

const CONTROLS = {
  speed: "dsp", pitch: "dsp", pause_before: "engine", pause_after: "engine",
  emotion: "dsp", delivery: "dsp", energy: "unsupported", emphasis: "unsupported",
} as const;
const VALUES = {
  emotion: ["angry", "calm", "curious", "excited", "happy", "sad", "surprised", "suspenseful"],
  delivery: ["energetic", "narrator", "podcast", "soft"],
};

const VOICES: VoiceSummary[] = [
  { voice_id: "male_calm", display_name: "Male — Calm Narrator", adapter_id: "nara-mini-v1", speaker: "htet-myat",
    supported_controls: { ...CONTROLS }, control_values: VALUES, note: "Expressions are prosody approximations (DSP)." },
  { voice_id: "female_warm", display_name: "Female — Warm Natural", adapter_id: "nara-mini-v1", speaker: "shoon",
    supported_controls: { ...CONTROLS }, control_values: VALUES, note: "Expressions are prosody approximations (DSP)." },
];

function toneWav(seconds: number): Uint8Array {
  const sr = 24000;
  const n = Math.floor(sr * seconds);
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const w = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const env = Math.min(1, i / 2000, (n - i) / 2000);
    v.setInt16(44 + i * 2, Math.sin((2 * Math.PI * 220 * i) / sr) * 6000 * env, true);
  }
  return new Uint8Array(buf);
}

export function createDemoClient(): StudioClient {
  const jobs = new Map<string, { info: JobInfo; polls: number }>();
  let counter = 0;
  const start = (kind: JobInfo["kind"], unsupported: string[], duration: number): JobInfo => {
    const id = `demo${++counter}`;
    const info: JobInfo = { job_id: id, kind, status: "queued", progress: 0, output_id: null, duration_s: null,
      unsupported, warnings: unsupported.map((u) => `Not applied (preview): ${u}`), error: null };
    jobs.set(id, { info: { ...info, duration_s: duration }, polls: 0 });
    return info;
  };
  const mcp: McpStatus = {
    server_command: "(preview) .venv-nara/Scripts/mvs-mcp.exe",
    server_available: true,
    clients: [
      { client: "claude_desktop", label: "Claude Desktop", enabled: false, config_path: "(preview) %APPDATA%/Claude/claude_desktop_config.json",
        config_exists: true, error: null, restart_note: "Claude Desktop ကို ပိတ်ပြီး ပြန်ဖွင့်မှ အသက်ဝင်ပါမယ်" },
      { client: "claude_code", label: "Claude Code (this project)", enabled: false, config_path: "(preview) <repo>/.mcp.json",
        config_exists: false, error: null, restart_note: "ဒီ folder မှာ Claude Code ပြန်ဖွင့်ပြီး server ကို approve လုပ်ပါ" },
    ],
  };
  const url = "http://127.0.0.1:17863/mcp";
  const http: McpHttpStatus = {
    running: false, url, port: 17863, error: null,
    tools: ["list_voices", "list_presets", "get_model_capabilities", "validate_voice_config", "preview_voice_direction",
      "generate_speech", "generate_directed_speech", "get_generation_status", "cancel_generation", "export_audio"],
    claude_code_command: `claude mcp add --transport http myanmar-voice-studio ${url}`,
    codex_command: `codex mcp add myanmar-voice-studio --url ${url}`,
  };
  const review: ReviewItem[] = [
    { file: "nr025.wav", status: "approved", text: "မင်္ဂလာပါ။ ကျွန်တော့်နာမည်က ကိုယ်ပိုင်အသံ ဖြစ်ပါတယ်။", heard: "မင်္ဂလာပါကျွန်တော့်နာမည်ကကိုယ်ပိုင်အသံဖြစ်ပါတယ်",
      script_id: "r001", script_text: "မင်္ဂလာပါ။ ကျွန်တော့်နာမည်က ကိုယ်ပိုင်အသံ ဖြစ်ပါတယ်။", ser: 0, duration_s: 4.1 },
    { file: "nr026.wav", status: "draft", text: "ဒီနေ့ရာသီဥတုအရမ်းလှတယ်", heard: "ဒီနေ့ရာသီဥတုအရမ်းလှတယ်",
      script_id: "r002", script_text: "ဒီနေ့ ရာသီဥတု အရမ်း လှပပါတယ်။", ser: 0.167, duration_s: 3.2 },
    { file: "nr068.wav", status: "draft", text: "ဒီမြို့ရဲ့သမိုင်းကတော့ကွာအလွန်ကြားရှည်ပါတယ်ကွာ", heard: "ဒီမြို့ရဲ့သမိုင်းကတော့ကွာအလွန်ကြားရှည်ပါတယ်ကွာ",
      script_id: "r017", script_text: "ဒီမြို့ရဲ့ သမိုင်းက အလွန် ရှည်ကြာပါတယ်။", ser: 0.417, duration_s: 4.4 },
  ];
  const reviewSummary = () => ({
    folder: "zayar_take2 (preview)", folders: ["zayar_take2 (preview)"], items: review.map((r) => ({ ...r })),
    approved: review.filter((r) => r.status === "approved").length,
    draft: review.filter((r) => r.status === "draft" || r.status === "missing").length,
    rejected: review.filter((r) => r.status === "rejected").length,
    approved_minutes: review.filter((r) => r.status === "approved").reduce((a, r) => a + r.duration_s, 0) / 60,
  });
  return {
    reviewSummary: async () => reviewSummary(),
    reviewAudio: async (_f, file) => toneWav(review.find((r) => r.file === file)?.duration_s ?? 2),
    reviewApprove: async (_f, file, text) => {
      const r = review.find((x) => x.file === file)!;
      Object.assign(r, { status: "approved", text: text.trim() });
      return { ...r };
    },
    reviewReject: async (_f, file, rejected) => {
      const r = review.find((x) => x.file === file)!;
      r.status = rejected ? "rejected" : "draft";
      return { ...r };
    },
    mcpHttpStatus: async () => ({ ...http }),
    mcpHttpSet: async (on) => { http.running = on; return { ...http }; },
    mcpStatus: async () => structuredClone(mcp),
    mcpSetEnabled: async (client, enabled) => {
      const c = mcp.clients.find((x) => x.client === client)!;
      c.enabled = enabled;
      c.config_exists = true;
      return { ...c };
    },
    listVoices: async () => VOICES,
    generateSpeech: async (r) => {
      const unsupported = [
        r.emotion && !VALUES.emotion.includes(r.emotion) && `emotion=${r.emotion}`,
        r.delivery && !VALUES.delivery.includes(r.delivery) && `delivery=${r.delivery}`,
      ].filter(Boolean) as string[];
      return start("speech", unsupported, Math.max(1.2, r.text.length / 12));
    },
    generateDirected: async () => start("directed", ["segment_001: emotion=curious"], 7.9),
    validate: async (config) => {
      const segs = ((config as { segments?: { id: string; emotion?: string; delivery?: string }[] }).segments ?? []);
      if (!segs.length) return { valid: false, errors: ["segments: List should have at least 1 item"], unsupported: [], warnings: [] };
      const unsupported = segs.flatMap((s) => [
        s.emotion && s.emotion !== "neutral" ? `${s.id}: emotion=${s.emotion}` : null,
        s.delivery && s.delivery !== "normal" ? `${s.id}: delivery=${s.delivery}` : null,
      ]).filter(Boolean) as string[];
      return { valid: true, errors: [], unsupported, warnings: [] };
    },
    status: async (id) => {
      const j = jobs.get(id);
      if (!j) throw new Error(`Unknown job_id '${id}'`);
      j.polls += 1;
      const progress = Math.min(1, j.polls / 4);
      j.info = { ...j.info, progress, status: progress >= 1 ? "completed" : "running", output_id: progress >= 1 ? id : null };
      return j.info;
    },
    cancel: async (id) => {
      const j = jobs.get(id)!;
      j.info = { ...j.info, status: "cancelled" };
      return j.info;
    },
    audio: async (id) => toneWav(jobs.get(id)?.info.duration_s ?? 1.5),
    exportWithDialog: async (id, name): Promise<ExportResult> => ({
      output_id: id, path: `(preview) ${name}.mp3`, format: "mp3", bytes: 0,
    }),
  };
}

export const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
