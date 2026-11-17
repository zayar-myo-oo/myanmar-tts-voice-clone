import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReviewItem, ReviewStatus, ReviewSummary, StudioClient } from "../api/types";
import { Icon, useToast } from "./shared";

type Filter = "todo" | "all" | ReviewStatus;

const STATUS: Record<ReviewStatus, { label: string; cls: string }> = {
  approved: { label: "✓ အတည်ပြုပြီး", cls: "bg-emerald-500/15 text-emerald-300" },
  draft: { label: "စစ်ရန်", cls: "bg-amber-500/15 text-amber-300" },
  missing: { label: "စာမရှိ", cls: "bg-amber-500/15 text-amber-300" },
  rejected: { label: "✗ ဖယ်ထား", cls: "bg-rose-500/15 text-rose-300" },
};

function ClipPlayer({ client, folder, file }: { client: StudioClient; folder: string; file: string }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let u: string | null = null;
    let alive = true;
    setUrl(null);
    client.reviewAudio(folder, file).then((b) => {
      if (!alive) return;
      u = URL.createObjectURL(new Blob([b], { type: "audio/wav" }));
      setUrl(u);
    });
    return () => {
      alive = false;
      if (u) URL.revokeObjectURL(u);
    };
  }, [client, folder, file]);
  return url ? (
    <audio data-testid="review-audio" ref={ref} src={url} controls autoPlay className="w-full" />
  ) : (
    <div className="h-10 animate-pulse rounded bg-white/5" />
  );
}

export function ReviewPanel({ client }: { client: StudioClient }) {
  const toast = useToast();
  const [data, setData] = useState<ReviewSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("todo");
  const [current, setCurrent] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    (folder?: string) =>
      client.reviewSummary(folder).then(setData).catch((e: Error) => setError(e.message)),
    [client],
  );
  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => {
    const items = data?.items ?? [];
    if (filter === "all") return items;
    if (filter === "todo") return items.filter((i) => i.status === "draft" || i.status === "missing");
    return items.filter((i) => i.status === filter);
  }, [data, filter]);

  const item = data?.items.find((i) => i.file === current) ?? null;
  useEffect(() => {
    if (!current && visible[0]) setCurrent(visible[0].file);
  }, [visible, current]);
  useEffect(() => { setText(item?.text ?? ""); }, [item?.file]); // eslint-disable-line react-hooks/exhaustive-deps

  function nextAfter(file: string) {
    const list = (data?.items ?? []).filter((i) => i.status === "draft" || i.status === "missing");
    const idx = list.findIndex((i) => i.file === file);
    return list[idx + 1]?.file ?? list.find((i) => i.file !== file)?.file ?? null;
  }

  async function act(fn: () => Promise<ReviewItem>, msg: string) {
    if (!item || !data) return;
    setBusy(true);
    try {
      const updated = await fn();
      const next = nextAfter(updated.file);
      await load(data.folder);
      toast("ok", msg);
      if (filter === "todo") setCurrent(next);
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const approve = (t: string) => item && data && act(() => client.reviewApprove(data.folder, item.file, t), `${item.file}: အတည်ပြုပြီး`);
  const reject = () => item && data && act(() => client.reviewReject(data.folder, item.file, item.status !== "rejected"),
    item.status === "rejected" ? `${item.file}: ပြန်ထည့်ပြီး` : `${item.file}: ဖယ်ထားပြီး`);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!item || busy) return;
      if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); void approve(text); }
      if (e.altKey && e.key.toLowerCase() === "s" && item.script_text) { e.preventDefault(); setText(item.script_text); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) return <p role="alert" className="text-rose-300">{error}</p>;
  if (!data) return <div className="card h-64 animate-pulse" />;
  const total = data.items.length;
  const pct = total ? Math.round(((data.approved + data.rejected) / total) * 100) : 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="burmese text-2xl font-semibold" style={{ lineHeight: 1.6 }}>အသံ စစ်ဆေး (Review)</h1>
          <p className="text-sm text-slate-400">ကိုယ့်အသံကို နားထောင်ပြီး ပြောခဲ့တဲ့အတိုင်း စာကို ပြင်ပါ။ အတည်ပြုထားတာကိုပဲ training မှာ သုံးပါမယ်။</p>
        </div>
        <select aria-label="folder" value={data.folder} onChange={(e) => { setCurrent(null); void load(e.target.value); }}
          className="rounded-lg border border-white/10 bg-slate-950 p-2 text-sm">
          {data.folders.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </header>

      <section className="card space-y-2 p-4 text-sm">
        <div className="flex flex-wrap gap-4">
          <span data-testid="review-counts">အတည်ပြု <b className="text-emerald-300">{data.approved}</b> · စစ်ရန် <b className="text-amber-300">{data.draft}</b> · ဖယ် <b className="text-rose-300">{data.rejected}</b> / {total}</span>
          <span className="ml-auto text-slate-400">အသုံးပြုနိုင်: <b className="text-slate-200">{data.approved_minutes.toFixed(1)}</b> / ၃၀ မိနစ်</span>
        </div>
        <div className="h-1.5 rounded-full bg-white/10"><div className="h-1.5 rounded-full bg-emerald-400" style={{ width: `${pct}%` }} /></div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <aside className="card flex max-h-[560px] flex-col overflow-hidden">
          <div className="flex gap-1 border-b border-white/5 p-2 text-xs" role="tablist">
            {(["todo", "approved", "rejected", "all"] as const).map((f) => (
              <button key={f} role="tab" aria-selected={filter === f} onClick={() => { setFilter(f); setCurrent(null); }}
                className={`rounded-lg px-2 py-1 ${filter === f ? "bg-sky-500/20 text-sky-200" : "text-slate-400 hover:bg-white/5"}`}>
                {{ todo: "စစ်ရန်", approved: "အတည်ပြုပြီး", rejected: "ဖယ်ထား", all: "အားလုံး" }[f]}
              </button>
            ))}
          </div>
          <ul className="flex-1 overflow-y-auto" aria-label="clips">
            {visible.length === 0 && <li className="p-4 text-sm text-slate-500">ဒီထဲမှာ မရှိတော့ပါ 🎉</li>}
            {visible.map((i) => (
              <li key={i.file}>
                <button onClick={() => setCurrent(i.file)} aria-current={i.file === current}
                  className={`w-full border-b border-white/5 px-3 py-2 text-left ${i.file === current ? "bg-sky-500/10" : "hover:bg-white/5"}`}>
                  <span className="flex items-center justify-between text-xs">
                    <span className="font-mono">{i.file}</span>
                    <span className={`rounded px-1.5 ${STATUS[i.status].cls}`}>{STATUS[i.status].label}</span>
                  </span>
                  <span className="burmese block truncate text-sm text-slate-300" style={{ lineHeight: 1.8 }}>{i.text || i.heard || "—"}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        {item ? (
          <section className="card space-y-4 p-5" aria-label="editor">
            <div className="flex items-center justify-between">
              <p className="font-mono text-sm">{item.file} <span className="text-slate-500">· {item.duration_s.toFixed(1)} s</span></p>
              <span className={`rounded px-2 py-0.5 text-xs ${STATUS[item.status].cls}`}>{STATUS[item.status].label}</span>
            </div>
            <ClipPlayer client={client} folder={data.folder} file={item.file} />
            <label className="block space-y-1">
              <span className="label">ပြောခဲ့တဲ့ စာ (ပြင်ပါ)</span>
              <textarea aria-label="transcript" value={text} onChange={(e) => setText(e.target.value)}
                className="burmese h-28 w-full rounded-xl border border-white/10 bg-slate-950 p-3 text-lg outline-none focus:border-sky-400" />
            </label>
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <div className="rounded-xl bg-white/[0.03] p-3">
                <p className="label">AI ကြားတာ (ASR)</p>
                <p className="burmese mt-1" style={{ lineHeight: 1.9 }}>{item.heard || "—"}</p>
              </div>
              <div className="rounded-xl bg-white/[0.03] p-3">
                <p className="label">Script {item.script_id ?? ""} {item.ser != null && <span className="normal-case text-slate-500">(ကွာခြားမှု {Math.round(item.ser * 100)}%)</span>}</p>
                <p className="burmese mt-1" style={{ lineHeight: 1.9 }}>{item.script_text || "—"}</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn-primary" disabled={busy || !text.trim()} onClick={() => approve(text)}>
                <Icon name="check" className="h-4 w-4" />အတည်ပြု
              </button>
              <button className="btn-ghost" disabled={busy || !item.script_text} onClick={() => setText(item.script_text)}>Script စာ သုံး</button>
              <button className="btn-ghost" disabled={busy || !item.heard} onClick={() => setText(item.heard)}>AI စာ သုံး</button>
              <button className="btn-ghost ml-auto" disabled={busy} onClick={reject}>
                {item.status === "rejected" ? "ပြန်ထည့်" : "ဖယ်ထား (မသုံး)"}
              </button>
            </div>
            <p className="text-xs text-slate-500">Ctrl+Enter = အတည်ပြု · Alt+S = Script စာ သုံး · ပြောခဲ့တဲ့ စကားလုံး အတိအကျ ဖြစ်ရပါမယ် (ဂဏန်းကို စာလုံးနဲ့)</p>
          </section>
        ) : (
          <section className="card grid place-items-center p-10 text-sm text-slate-500">ဘယ်ဘက်က ဖိုင် တစ်ခု ရွေးပါ</section>
        )}
      </div>
    </div>
  );
}
