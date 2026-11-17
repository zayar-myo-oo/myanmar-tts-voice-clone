import { useMemo, useState } from "react";
import example from "../../../../schemas/examples/stickman-story.json";
import { waitForJob } from "../api/client";
import type { JobInfo, StudioClient, ValidationReport, VoiceSummary } from "../api/types";
import type { HistoryItem } from "./HistoryPanel";
import { AudioPlayer, Icon, NotApplied, ProgressBar, useExport } from "./shared";

interface SegmentView {
  id: string;
  text: string;
  voice_id?: string | null;
  emotion?: string | null;
  delivery?: string | null;
  pause_after_ms?: number;
}

function parse(source: string): { doc: Record<string, unknown> | null; error: string | null } {
  try {
    return { doc: JSON.parse(source) as Record<string, unknown>, error: null };
  } catch (e) {
    return { doc: null, error: (e as Error).message };
  }
}

interface Props {
  client: StudioClient;
  voices: VoiceSummary[];
  onDone: (item: HistoryItem) => void;
}

/** Voice-direction script (schema 1.0): segment table + JSON editor, validate, render. */
export function ScriptPanel({ client, voices, onDone }: Props) {
  const exportAudio = useExport(client);
  const [source, setSource] = useState(JSON.stringify(example, null, 2));
  const [view, setView] = useState<"table" | "json">("table");
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsed = useMemo(() => parse(source), [source]);
  const doc = parsed.doc;
  const segments = (Array.isArray(doc?.segments) ? doc!.segments : []) as SegmentView[];
  const defaultVoice = typeof doc?.voice_id === "string" ? doc.voice_id : "";
  const voiceName = (id: string) => voices.find((v) => v.voice_id === id)?.display_name ?? id;
  const flagsFor = (id: string) =>
    (report?.unsupported ?? []).filter((u) => u.startsWith(`${id}:`)).map((u) => u.slice(id.length + 2));

  async function validate(): Promise<ValidationReport | null> {
    setError(null);
    if (!doc) {
      setError(`JSON မမှန်ပါ: ${parsed.error}`);
      return null;
    }
    const r = await client.validate(doc);
    setReport(r);
    return r;
  }

  async function renderScript() {
    setBusy(true);
    setJob(null);
    try {
      const check = await validate();
      if (!check?.valid || !doc) return;
      const done = await waitForJob(client, await client.generateDirected(doc), setJob);
      if (done.status === "completed" && done.output_id) {
        onDone({ id: done.job_id, kind: "directed", title: String(doc.project_name ?? "Script"),
          voiceName: voiceName(defaultVoice), outputId: done.output_id, duration: done.duration_s ?? 0,
          unsupported: done.unsupported, createdAt: Date.now() });
      } else if (done.status === "failed") setError(done.error);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="burmese text-2xl font-semibold" style={{ lineHeight: 1.6 }}>ဇာတ်ညွှန်း (Voice Direction)</h1>
          <p className="text-sm text-slate-400">Segment တစ်ခုချင်းစီကို voice၊ ရပ်နားချိန် သတ်မှတ်ပြီး ဖိုင်တစ်ခုတည်း ထုတ်ပါ။ Schema 1.0</p>
        </div>
        <div className="flex rounded-xl bg-white/5 p-1 text-sm" role="tablist">
          {(["table", "json"] as const).map((v) => (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => setView(v)}
              className={`rounded-lg px-3 py-1 ${view === v ? "bg-sky-500/20 text-sky-200" : "text-slate-400"}`}>
              {v === "table" ? "Segments" : "JSON"}
            </button>
          ))}
        </div>
      </header>

      {view === "json" ? (
        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-white/5 px-4 py-2 text-xs text-slate-400">
            <span>{parsed.error ? <span className="text-rose-300">JSON error: {parsed.error}</span> : "JSON OK"}</span>
            <button disabled={!doc} className="hover:text-slate-200 disabled:opacity-40"
              onClick={() => doc && setSource(JSON.stringify(doc, null, 2))}>Format</button>
          </div>
          <textarea aria-label="script-json" spellCheck={false} value={source} onChange={(e) => setSource(e.target.value)}
            className="h-[420px] w-full resize-y bg-transparent p-4 font-mono text-[13px] leading-relaxed outline-none" />
        </section>
      ) : (
        <section className="card overflow-hidden" aria-label="segments">
          {!doc ? (
            <p className="p-6 text-sm text-rose-300">JSON မမှန်လို့ segment တွေ မပြနိုင်ပါ — JSON tab မှာ ပြင်ပါ ({parsed.error})</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-white/[0.03] text-left text-xs text-slate-400">
                <tr><th className="px-4 py-2">#</th><th className="px-2 py-2">Segment</th><th className="px-2 py-2">Voice</th><th className="px-2 py-2">Pause</th><th className="px-4 py-2">Notes</th></tr>
              </thead>
              <tbody>
                {segments.map((s, i) => {
                  const flags = flagsFor(s.id);
                  return (
                    <tr key={s.id ?? i} className="border-t border-white/5 align-top">
                      <td className="px-4 py-3 text-slate-500">{i + 1}</td>
                      <td className="px-2 py-3">
                        <p className="burmese" style={{ lineHeight: 1.9 }}>{s.text}</p>
                        <p className="text-[11px] text-slate-500">{s.id}{s.emotion ? ` · ${s.emotion}` : ""}{s.delivery ? ` · ${s.delivery}` : ""}</p>
                      </td>
                      <td className="whitespace-nowrap px-2 py-3 text-slate-300">{voiceName(s.voice_id ?? defaultVoice)}</td>
                      <td className="px-2 py-3 tabular-nums text-slate-400">{s.pause_after_ms ?? 0} ms</td>
                      <td className="px-4 py-3">
                        {flags.map((f) => <span key={f} className="mb-1 mr-1 inline-block rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[11px] text-amber-300">{f} ✗</span>)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-ghost" onClick={validate}><Icon name="check" className="h-4 w-4" />Validate / Preview</button>
        <button className="btn-primary" disabled={busy} onClick={renderScript}>
          <Icon name="mic" className="h-4 w-4" />{busy ? `Render လုပ်နေသည်… ${Math.round((job?.progress ?? 0) * 100)}%` : "Render script"}
        </button>
        {busy && job && <button className="btn-ghost" onClick={() => client.cancel(job.job_id).then(setJob)}>Cancel</button>}
        {report && (
          <span data-testid="report" className={`text-sm ${report.valid ? "text-emerald-300" : "text-rose-300"}`}>
            {report.valid ? `✓ Valid · ${segments.length} segments` : `✗ ${report.errors.join("; ")}`}
            {report.valid && report.unsupported.length > 0 && <span className="ml-2 text-amber-300">· {report.unsupported.length} control(s) not applicable — Notes column</span>}
          </span>
        )}
      </div>
      {busy && job && <ProgressBar job={job} />}
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}

      {job?.status === "completed" && job.output_id && (
        <section className="card space-y-4 p-5" aria-label="result">
          <div className="flex items-center justify-between">
            <p className="font-medium">{String(doc?.project_name ?? "Script")} <span className="text-xs text-slate-400">· {job.duration_s?.toFixed(2)} s</span></p>
            <button className="btn-primary" onClick={() => exportAudio(job.output_id!, "script")}><Icon name="download" className="h-4 w-4" />Export</button>
          </div>
          <AudioPlayer client={client} outputId={job.output_id} autoPlay />
          <NotApplied items={job.unsupported} />
        </section>
      )}
    </div>
  );
}
