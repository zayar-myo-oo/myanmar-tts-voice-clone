import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { JobInfo, StudioClient, Support } from "../api/types";

/* ---------- icons (inline SVG, no icon library) ---------- */
const path = {
  play: "M8 5v14l11-7z",
  pause: "M6 5h4v14H6zM14 5h4v14h-4z",
  mic: "M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-2.1A7 7 0 0 0 19 12z",
  script: "M4 4h12l4 4v12H4zM8 11h8M8 15h8M8 7h4",
  history: "M12 8v4l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4",
  download: "M12 3v12m0 0 4-4m-4 4-4-4M4 19h16",
  redo: "M4 12a8 8 0 0 1 14-5.3M20 4v5h-5M20 12a8 8 0 0 1-14 5.3M4 20v-5h5",
  x: "M6 6l12 12M18 6 6 18",
  check: "M5 12l4 4L19 6",
  warn: "M12 3 2 20h20zM12 9v5M12 17v.5",
  info: "M12 8v.5M11 11h1v6h1M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  plug: "M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4",
} as const;

export function Icon({ name, className = "h-5 w-5" }: { name: keyof typeof path; className?: string }) {
  const filled = name === "play" || name === "pause" || name === "mic";
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={path[name]} />
    </svg>
  );
}

/* ---------- capability badge ---------- */
const SUPPORT: Record<Support, { text: string; cls: string; title: string }> = {
  native: { text: "native", cls: "bg-emerald-500/15 text-emerald-300", title: "Model ကိုယ်တိုင် ထုတ်ပေးသည်" },
  dsp: { text: "DSP", cls: "bg-sky-500/15 text-sky-300", title: "အသံထွက်ပြီးမှ ပြင်ဆင်ခြင်း (post-processing)" },
  engine: { text: "engine", cls: "bg-violet-500/15 text-violet-300", title: "Engine က ထည့်ပေးသည် (ဥပမာ အသံတိတ်)" },
  unsupported: { text: "မရပါ", cls: "bg-rose-500/15 text-rose-300", title: "ဒီအသံအတွက် မလုပ်ပေးနိုင်ပါ" },
};

export function SupportBadge({ support }: { support: Support | undefined }) {
  const s = SUPPORT[support ?? "unsupported"];
  return <span title={s.title} className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${s.cls}`}>{s.text}</span>;
}

/* ---------- toasts ---------- */
type Toast = { id: number; kind: "ok" | "error" | "info"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} role="status"
            className={`pointer-events-auto flex items-start gap-2 rounded-xl border px-3 py-2 text-sm shadow-xl backdrop-blur ${
              t.kind === "ok" ? "border-emerald-500/30 bg-emerald-950/80" : t.kind === "error" ? "border-rose-500/30 bg-rose-950/80" : "border-white/10 bg-slate-900/90"}`}>
            <Icon name={t.kind === "ok" ? "check" : t.kind === "error" ? "warn" : "info"} className="mt-0.5 h-4 w-4 shrink-0" />
            <span className="break-all">{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- not-applied notice ---------- */
export function NotApplied({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-amber-200">
      <Icon name="warn" className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="font-medium">ဒီအသံမှာ မလုပ်ပေးနိုင်ခဲ့တာ (not applied)</p>
        <p className="mt-1 text-amber-200/80">{items.join(" · ")}</p>
      </div>
    </div>
  );
}

/* ---------- audio player ---------- */
const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function AudioPlayer({ client, outputId, autoPlay = false }: { client: StudioClient; outputId: string; autoPlay?: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  useEffect(() => {
    let objectUrl: string | null = null;
    let alive = true;
    setUrl(null);
    client.audio(outputId)
      .then((bytes) => {
        if (!alive) return;
        objectUrl = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
        setUrl(objectUrl);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [client, outputId]);

  if (error) return <p className="text-sm text-rose-300">အသံဖွင့်လို့ မရပါ: {error}</p>;
  const pct = duration ? (time / duration) * 100 : 0;
  return (
    <div className="flex items-center gap-3" data-testid="player">
      <button aria-label={playing ? "pause" : "play"} disabled={!url}
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-sky-500 text-slate-950 hover:bg-sky-400 disabled:opacity-40"
        onClick={() => (playing ? ref.current?.pause() : ref.current?.play())}>
        <Icon name={playing ? "pause" : "play"} />
      </button>
      <div className="flex-1">
        <div className="group relative h-2 cursor-pointer rounded-full bg-white/10"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            if (ref.current && duration) ref.current.currentTime = ((e.clientX - r.left) / r.width) * duration;
          }}>
          <div className="absolute inset-y-0 left-0 rounded-full bg-sky-400" style={{ width: `${pct}%` }} />
        </div>
        <div className="mt-1 flex justify-between text-[11px] tabular-nums text-slate-400">
          <span>{fmt(time)}</span><span>{fmt(duration)}</span>
        </div>
      </div>
      {url && (
        <audio ref={ref} src={url} autoPlay={autoPlay} preload="auto"
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)} />
      )}
    </div>
  );
}

export function useExport(client: StudioClient) {
  const toast = useToast();
  return async (outputId: string, name: string) => {
    try {
      const r = await client.exportWithDialog(outputId, name);
      if (r) toast("ok", `သိမ်းပြီးပါပြီ: ${r.path}`);
    } catch (e) {
      toast("error", `သိမ်းလို့ မရပါ: ${(e as Error).message}`);
    }
  };
}

export function ProgressBar({ job }: { job: JobInfo }) {
  return (
    <div className="h-1 overflow-hidden rounded-full bg-white/10">
      <div className="h-1 rounded-full bg-sky-400 transition-all duration-300" style={{ width: `${Math.round(job.progress * 100)}%` }} />
    </div>
  );
}
