import { useState } from "react";
import type { StudioClient } from "../api/types";
import { AudioPlayer, Icon, useExport } from "./shared";

export interface HistoryItem {
  id: string;
  kind: "speech" | "directed";
  title: string;
  voiceName: string;
  outputId: string;
  duration: number;
  unsupported: string[];
  createdAt: number;
}

export function HistoryPanel({ client, items, onClear }: { client: StudioClient; items: HistoryItem[]; onClear: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const exportAudio = useExport(client);
  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="burmese text-2xl font-semibold" style={{ lineHeight: 1.6 }}>မှတ်တမ်း</h1>
          <p className="text-sm text-slate-400">ဒီ session မှာ ထုတ်ခဲ့တဲ့ အသံများ။ App ပိတ်ရင် ပျောက်ပါမယ် (SQLite history နောက်မှ ထည့်မယ်)။</p>
        </div>
        {items.length > 0 && <button className="btn-ghost" onClick={onClear}>ရှင်းမယ်</button>}
      </header>
      {items.length === 0 ? (
        <div className="card grid h-48 place-items-center text-sm text-slate-500">မှတ်တမ်း မရှိသေးပါ — အသံထုတ်ကြည့်ပါ</div>
      ) : (
        <ul className="space-y-3">
          {items.map((h) => (
            <li key={h.id} className="card p-4">
              <div className="flex items-center gap-4">
                <button aria-label={`open ${h.id}`} onClick={() => setOpen(open === h.id ? null : h.id)}
                  className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/5 hover:bg-white/10">
                  <Icon name={open === h.id ? "x" : "play"} className="h-4 w-4" />
                </button>
                <div className="min-w-0 flex-1">
                  <p className="burmese truncate" style={{ lineHeight: 1.8 }}>{h.title}</p>
                  <p className="text-xs text-slate-400">
                    {h.kind === "directed" ? "Script" : "TTS"} · {h.voiceName} · {h.duration.toFixed(1)} s ·{" "}
                    {new Date(h.createdAt).toLocaleTimeString()}
                    {h.unsupported.length > 0 && <span className="ml-2 text-amber-300">{h.unsupported.length} not applied</span>}
                  </p>
                </div>
                <button className="btn-ghost" onClick={() => exportAudio(h.outputId, `voice-${h.outputId}`)}>
                  <Icon name="download" className="h-4 w-4" />Export
                </button>
              </div>
              {open === h.id && <div className="mt-4"><AudioPlayer client={client} outputId={h.outputId} autoPlay /></div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
