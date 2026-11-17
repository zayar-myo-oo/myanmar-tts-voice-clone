import { useEffect, useState } from "react";
import { waitForJob } from "../api/client";
import type { JobInfo, StudioClient, VoiceSummary } from "../api/types";
import { WorkerError } from "../api/types";
import type { HistoryItem } from "./HistoryPanel";
import { AudioPlayer, Icon, NotApplied, ProgressBar, SupportBadge, useExport, useToast } from "./shared";

const EMOTIONS = ["curious", "excited", "calm", "angry", "sad", "suspenseful", "happy", "surprised"];
const DELIVERIES = ["soft", "whisper", "shout", "narrator", "podcast", "energetic"];
const SAMPLES = [
  "မင်္ဂလာပါ။ ဒီနေ့ နေကောင်းလား။",
  "ကမ္ဘာကြီးက တည်ရှိနေတာ ကြာပြီ။",
  "မင်းသိလား။ ဒီအကြောင်းကို ဘယ်သူ ပြောပြတာလဲ။",
];

const DRAFT_KEY = "mvs-studio-draft-v1";
function readDraft(): string {
  try { return localStorage.getItem(DRAFT_KEY) ?? SAMPLES[1]!; }
  catch { return SAMPLES[1]!; }
}

function voiceMeta(v: VoiceSummary) {
  const female = /female/i.test(v.display_name);
  const male = /male/i.test(v.display_name) && !female;
  const [, style = v.display_name] = v.display_name.split("—").map((s) => s.trim());
  return { gender: male ? "ကျား" : female ? "မ" : "ကိုယ်ပိုင်", style,
    initial: male ? "M" : female ? "F" : "V",
    tone: male ? "from-sky-500 to-indigo-600" : female ? "from-pink-500 to-orange-400" : "from-teal-500 to-emerald-600" };
}

interface Props {
  client: StudioClient;
  voices: VoiceSummary[];
  onDone: (item: HistoryItem) => void;
}

export function StudioPanel({ client, voices, onDone }: Props) {
  const toast = useToast();
  const exportAudio = useExport(client);
  const [text, setText] = useState(readDraft);
  const [clearedText, setClearedText] = useState<string | null>(null);
  const [draftSaved, setDraftSaved] = useState(false);
  const [resultVoice, setResultVoice] = useState("");
  const [voiceId, setVoiceId] = useState(voices[0]?.voice_id ?? "");
  const [speed, setSpeed] = useState(1);
  const [pitch, setPitch] = useState(0);
  const [pauseAfter, setPauseAfter] = useState(0);
  const [emotion, setEmotion] = useState("");
  const [delivery, setDelivery] = useState("");
  const [strict, setStrict] = useState(false);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const voice = voices.find((v) => v.voice_id === voiceId);
  const sup = (c: string) => voice?.supported_controls[c] ?? "unsupported";
  const allowed = (c: string) => voice?.control_values?.[c];

  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, text); setDraftSaved(true); }
    catch { setDraftSaved(false); }
  }, [text]);

  async function generate() {
    if (busy || !text.trim()) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const started = await client.generateSpeech({
        text, voice_id: voiceId, speed, pitch_semitones: pitch, pause_after_ms: pauseAfter,
        emotion: emotion || null, delivery: delivery || null, strict,
      });
      const done = await waitForJob(client, started, setJob);
      if (done.status === "cancelled") toast("info", "ရပ်လိုက်ပါပြီ (cancelled)");
      if (done.status === "completed" && done.output_id) {
        setResultVoice(voice?.display_name ?? voiceId);
        onDone({ id: done.job_id, kind: "speech", title: text, voiceName: voice?.display_name ?? voiceId,
          outputId: done.output_id, duration: done.duration_s ?? 0, unsupported: done.unsupported, createdAt: Date.now() });
      } else if (done.status === "failed") {
        setError(done.error ?? "Generation failed");
      }
    } catch (e) {
      const we = e as WorkerError;
      setError(we.type === "UnsupportedControlError" ? `Strict mode — ထုတ်မပေးပါ: ${we.message}` : we.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        void generate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const reset = () => { setSpeed(1); setPitch(0); setPauseAfter(0); setEmotion(""); setDelivery(""); setStrict(false); };
  const done = job?.status === "completed" && job.output_id;

  return (
    <div className="space-y-6">
      <header className="studio-heading">
        <p className="mb-2 text-xs font-semibold tracking-[0.2em] text-sky-300">MYANMAR VOICE STUDIO</p>
        <h1 className="burmese text-3xl font-semibold" style={{ lineHeight: 1.6 }}>သင့်စာသားကို အသံအဖြစ် ပြောင်းလိုက်ပါ</h1>
        <p className="mt-2 text-sm leading-7 text-slate-400">အသံရွေးပါ၊ စာရေးပါ၊ ပြီးရင် နားထောင်ပြီး သိမ်းဆည်းပါ။</p>
        <ol aria-label="လုပ်ဆောင်ရန် အဆင့်များ" className="mt-5 flex flex-wrap gap-3 text-xs text-slate-300">
          {["အသံရွေး", "စာသားရေး", "နားထောင်ပြီး သိမ်းဆည်း"].map((label, i) => (
            <li key={label} className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-2">
              <span className="grid h-5 w-5 place-items-center rounded-full bg-sky-400/15 text-sky-300">{i + 1}</span>{label}
            </li>
          ))}
        </ol>
      </header>

      {/* voice cards */}
      <section aria-label="voices" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" role="radiogroup">
        {voices.map((v) => {
          const m = voiceMeta(v);
          const active = v.voice_id === voiceId;
          return (
            <button key={v.voice_id} role="radio" aria-checked={active} aria-label={v.display_name}
              disabled={busy}
              onClick={() => setVoiceId(v.voice_id)}
              className={`card flex items-center gap-3 p-4 text-left transition ${active ? "ring-2 ring-sky-400" : "hover:border-white/15"}`}>
              <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-full bg-gradient-to-br ${m.tone} font-semibold text-white`}>{m.initial}</span>
              <span className="min-w-0">
                <span className="block font-medium">{m.style}</span>
                <span className="mt-1 block text-xs text-slate-400">{m.gender}အသံ · {active ? "ရွေးထားသည်" : "ရွေးရန် နှိပ်ပါ"}</span>
              </span>
              {active && <Icon name="check" className="ml-auto h-5 w-5 text-sky-300" />}
            </button>
          );
        })}
      </section>

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        {/* editor + result */}
        <div className="space-y-6">
        <section className="card flex flex-col">
          <div className="flex items-center justify-between border-b border-white/5 px-5 py-4">
            <label htmlFor="studio-text" className="burmese font-medium">ဖတ်စေချင်သော စာသား</label>
            <span role="status" className="text-xs text-slate-400">{draftSaved ? "စာမူ သိမ်းထားပြီး" : "စာမူ မသိမ်းနိုင်သေးပါ"}</span>
          </div>
          <textarea id="studio-text" aria-label="text" aria-describedby="text-help" disabled={busy} value={text} maxLength={2000} onChange={(e) => setText(e.target.value)}
            placeholder="ဒီမှာ မြန်မာစာ ရိုက်ပါ…"
            className="burmese min-h-[260px] resize-y bg-transparent p-5 text-lg outline-none placeholder:text-slate-500 disabled:opacity-70" />
          <p id="text-help" className="px-5 pb-3 text-xs leading-6 text-slate-400">ဝါကျတွေကို ။ နဲ့ ခွဲရေးပါ။ စာသားကို ဒီစက်ထဲမှာပဲ အလိုအလျောက် သိမ်းထားပါတယ်။</p>
          <div className="flex flex-wrap items-center gap-2 border-t border-white/5 px-4 py-3">
            <span className="label mr-1">နမူနာ</span>
            {SAMPLES.map((s) => (
              <button key={s} disabled={busy} onClick={() => { setClearedText(text); setText(s); }} className="burmese truncate rounded-lg bg-white/5 px-2 py-0.5 text-xs hover:bg-white/10" style={{ maxWidth: 180, lineHeight: 1.8 }}>{s}</button>
            ))}
            <span className="ml-auto text-xs tabular-nums text-slate-500">{text.length}/2000</span>
            <button disabled={busy || !text} onClick={() => { setClearedText(text); setText(""); }} className="text-xs text-slate-400 hover:text-slate-200 disabled:opacity-40">ရှင်းမယ်</button>
            {clearedText !== null && <button disabled={busy} className="text-xs text-sky-300" onClick={() => { setText(clearedText); setClearedText(null); }}>မူလစာ ပြန်ယူမယ်</button>}
          </div>
          <div className="space-y-3 border-t border-white/5 p-4">
            <div className="flex items-center gap-3">
              <button className="btn-primary px-6 py-2.5 text-base" disabled={busy || !text.trim() || !voiceId} onClick={generate}>
                <Icon name="mic" className="h-4 w-4" />
                {busy ? `ထုတ်နေသည်… ${Math.round((job?.progress ?? 0) * 100)}%` : "အသံထုတ်မယ်"}
              </button>
              {busy && job && (
                <button className="btn-ghost" onClick={() => client.cancel(job.job_id).then(setJob).catch((e: Error) => setError(e.message))}>ရပ်မယ်</button>
              )}
              <span className="ml-auto text-xs text-slate-500">Ctrl + Enter</span>
            </div>
            {busy && job && <ProgressBar job={job} />}
            {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
          </div>
        </section>
        {done && job.output_id && (
          <section className="card space-y-4 p-5" aria-label="result">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium text-emerald-300">အသံထုတ်ပြီးပါပြီ <span data-testid="job-status" className="sr-only">{job.status}</span></p>
                <p className="mt-1 text-xs text-slate-400">{resultVoice} · {job.duration_s?.toFixed(2)} s</p>
              </div>
              <div className="flex gap-2">
                <button className="btn-ghost" onClick={generate} disabled={busy}><Icon name="redo" className="h-4 w-4" />ပြန်ထုတ်</button>
                <button className="btn-primary" onClick={() => exportAudio(job.output_id!, `voice-${job.output_id}`)}>
                  <Icon name="download" className="h-4 w-4" />သိမ်းမယ် · Export
                </button>
              </div>
            </div>
            <AudioPlayer client={client} outputId={job.output_id} autoPlay />
            <NotApplied items={job.unsupported} />
          </section>
        )}
        {!done && !busy && !error && <div className="rounded-2xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400">
          <Icon name="play" className="mx-auto mb-3 h-6 w-6 text-slate-500" />
          ထုတ်ပြီးတဲ့အသံကို ဒီနေရာမှာ နားထောင်ပြီး WAV / MP3 အဖြစ် သိမ်းနိုင်ပါတယ်။
        </div>}
        </div>

        {/* controls */}
        <aside className="card h-fit p-5 text-sm lg:sticky lg:top-6">
        <fieldset disabled={busy} className="space-y-5 disabled:opacity-60">
          <div className="flex items-center justify-between">
            <span className="burmese font-medium">အသံ ချိန်ညှိရန်</span>
            <button onClick={reset} className="text-xs text-sky-300 hover:text-sky-200">မူလအတိုင်း</button>
          </div>
          <Slider label="အမြန်နှုန်း" value={`${speed.toFixed(2)}×`} support={sup("speed")}>
            <input aria-label="speed" type="range" min={0.5} max={2} step={0.05} value={speed} onChange={(e) => setSpeed(+e.target.value)} />
          </Slider>
          <Slider label="အသံ အနိမ့် / အမြင့်" value={`${pitch > 0 ? "+" : ""}${pitch} st`} support={sup("pitch")}>
            <input aria-label="pitch" type="range" min={-6} max={6} step={0.5} value={pitch} onChange={(e) => setPitch(+e.target.value)} />
          </Slider>
          <Slider label="အဆုံးတွင် ရပ်နားချိန်" value={`${(pauseAfter / 1000).toFixed(1)} s`} support={sup("pause_after")}>
            <input aria-label="pause" type="range" min={0} max={3000} step={50} value={pauseAfter} onChange={(e) => setPauseAfter(+e.target.value)} />
          </Slider>

          <div className="space-y-3 rounded-xl bg-white/[0.03] p-3">
            <p className="burmese font-medium">ပြောဟန်နှင့် ခံစားချက်</p>
            <Select label="Emotion" value={emotion} onChange={setEmotion} options={EMOTIONS} allowed={allowed("emotion")} support={sup("emotion")} />
            <Select label="Delivery" value={delivery} onChange={setDelivery} options={DELIVERIES} allowed={allowed("delivery")} support={sup("delivery")} />
            <p className="text-xs leading-relaxed text-slate-400">
              Expression တွေကို အမြန်နှုန်း၊ အသံအနိမ့်အမြင့်၊ ရပ်နားချိန်၊ အသံကျယ်/တိုး ပြောင်းပြီး ဖန်တီးပါတယ် (DSP)။
              သရုပ်ဆောင်ထားတဲ့ ခံစားချက် အစစ် မဟုတ်ပါ။ "(မရ)" ပါတဲ့ whisper/shout ကို ရွေးရင် အသံ မပြောင်းဘဲ "not applied" ပြပါမယ်။
            </p>
          </div>
          <label className="flex items-start gap-2 text-xs text-slate-300">
            <input type="checkbox" className="mt-0.5 accent-sky-400" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
            <span>Strict — မရတဲ့ control ပါရင် လုံးဝ မထုတ်ပါ</span>
          </label>
        </fieldset>
        </aside>
      </div>

    </div>
  );
}

function Slider({ label, value, support, children }: { label: string; value: string; support: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="flex items-center justify-between">
        <span className="flex items-center gap-2">{label}<SupportBadge support={support as never} /></span>
        <span className="tabular-nums text-slate-400">{value}</span>
      </span>
      {children}
    </label>
  );
}

function Select({ label, value, onChange, options, allowed, support }: {
  label: string; value: string; onChange: (v: string) => void; options: string[]; allowed?: string[]; support: string;
}) {
  const ok = (o: string) => support !== "unsupported" && (!allowed || allowed.includes(o));
  const off = value !== "" && !ok(value);
  return (
    <label className="block space-y-1.5">
      <span className="flex items-center gap-2">{label}<SupportBadge support={support as never} /></span>
      <select aria-label={label.toLowerCase()} value={value} onChange={(e) => onChange(e.target.value)}
        className={`w-full rounded-lg border bg-slate-950 p-2 ${off ? "border-amber-500/40 text-amber-300" : "border-white/10"}`}>
        <option value="">— none —</option>
        {options.map((o) => <option key={o} value={o}>{ok(o) ? o : `${o} (မရ)`}</option>)}
      </select>
    </label>
  );
}
