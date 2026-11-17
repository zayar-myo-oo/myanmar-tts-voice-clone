import { useCallback, useEffect, useState } from "react";
import type { StudioClient, VoiceSummary } from "./api/types";
import { HistoryPanel, type HistoryItem } from "./components/HistoryPanel";
import { McpPanel, rememberedHttpOn } from "./components/McpPanel";
import { ReviewPanel } from "./components/ReviewPanel";
import { ScriptPanel } from "./components/ScriptPanel";
import { Icon, ToastProvider } from "./components/shared";
import { StudioPanel } from "./components/StudioPanel";

type Page = "studio" | "script" | "history" | "review" | "mcp";

const NAV: { id: Page; label: string; sub: string; icon: "mic" | "script" | "history" | "plug" | "check" }[] = [
  { id: "studio", label: "အသံထုတ်", sub: "Text-to-Speech", icon: "mic" },
  { id: "script", label: "ဇာတ်ညွှန်း", sub: "Voice Direction", icon: "script" },
  { id: "history", label: "မှတ်တမ်း", sub: "History", icon: "history" },
  { id: "review", label: "အသံ စစ်ဆေး", sub: "Own-voice review", icon: "check" },
  { id: "mcp", label: "Connections", sub: "MCP · AI tools", icon: "plug" },
];

export default function App({ client, preview = false }: { client: StudioClient; preview?: boolean }) {
  const [voices, setVoices] = useState<VoiceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<Page>("studio");
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [mcpOn, setMcpOn] = useState(false);
  useEffect(() => {
    // Restore the user's last choice: start the local MCP endpoint if it was on.
    const restore = rememberedHttpOn() ? client.mcpHttpSet(true) : client.mcpHttpStatus();
    restore.then((s) => setMcpOn(s.running)).catch(() => setMcpOn(false));
  }, [client]);

  const connect = useCallback(() => {
    setError(null);
    client.listVoices().then(setVoices).catch((e: Error) => setError(e.message));
  }, [client]);
  useEffect(connect, [connect]);

  const addHistory = useCallback((item: HistoryItem) => setHistory((h) => [item, ...h].slice(0, 100)), []);
  const status = error ? "error" : voices ? "ready" : "loading";

  return (
    <ToastProvider>
      <div className="flex h-full">
        <aside className="flex w-48 shrink-0 flex-col border-r border-white/10 bg-slate-950/60 p-3 xl:w-60 xl:p-4">
          <div className="mb-8 flex items-center gap-3 px-2">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-sky-400 to-indigo-500 text-slate-950">
              <Icon name="mic" className="h-5 w-5" />
            </div>
            <div className="leading-tight">
              <p className="font-semibold">Voice Studio</p>
              <p className="text-[11px] text-slate-400">မြန်မာ AI အသံ</p>
            </div>
          </div>
          <nav className="flex flex-col gap-1" aria-label="main">
            {NAV.map((n) => (
              <button key={n.id} onClick={() => setPage(n.id)} aria-current={page === n.id ? "page" : undefined}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition ${
                  page === n.id ? "bg-sky-500/15 text-sky-200" : "text-slate-300 hover:bg-white/5"}`}>
                <Icon name={n.icon} className="h-5 w-5" />
                <span className="leading-tight">
                  <span className="burmese block text-sm" style={{ lineHeight: 1.6 }}>{n.label}</span>
                  <span className="block text-[11px] text-slate-500">{n.sub}</span>
                </span>
                {n.id === "mcp" && (
                  <span data-testid="mcp-badge" className={`ml-auto rounded-full px-2 text-[10px] font-semibold ${mcpOn ? "bg-emerald-500/20 text-emerald-300" : "bg-white/10 text-slate-400"}`}>
                    {mcpOn ? "ON" : "OFF"}
                  </span>
                )}
                {n.id === "history" && history.length > 0 && (
                  <span className="ml-auto rounded-full bg-white/10 px-2 text-[11px]">{history.length}</span>
                )}
              </button>
            ))}
          </nav>
          <div className="mt-auto space-y-2 rounded-xl bg-white/[0.03] p-3 text-xs" data-testid="engine-status">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${status === "ready" ? "bg-emerald-400" : status === "error" ? "bg-rose-400" : "animate-pulse bg-amber-400"}`} />
              <span>{status === "ready" ? "Engine အဆင်သင့်" : status === "error" ? "Engine မချိတ်မိပါ" : "Engine ဖွင့်နေသည်…"}</span>
            </div>
            <p className="text-slate-500">Offline · {voices?.length ?? 0} voices · MCP {mcpOn ? "ON" : "OFF"}</p>
            {preview && <p className="rounded-md bg-amber-500/10 px-2 py-1 text-amber-300">Preview mode — အသံအတု</p>}
          </div>
        </aside>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl p-5 xl:p-8">
            {error && (
              <div role="alert" className="card flex items-start gap-4 border-rose-500/20 p-5">
                <Icon name="warn" className="h-6 w-6 text-rose-300" />
                <div className="flex-1">
                  <p className="font-semibold">Voice engine နဲ့ ချိတ်လို့ မရပါ</p>
                  <p className="mt-1 text-sm text-slate-300">{error}</p>
                  <p className="mt-2 text-xs text-slate-500">MVS_WORKER (mvs-worker.exe) နဲ့ MVS_PROJECT_ROOT ကို စစ်ပါ။</p>
                </div>
                <button className="btn-ghost" onClick={connect}>ပြန်ချိတ်မယ်</button>
              </div>
            )}
            {!error && !voices && page !== "mcp" && page !== "review" && <div className="card h-64 animate-pulse" aria-label="loading" />}
            {voices && page === "studio" && <StudioPanel client={client} voices={voices} onDone={addHistory} />}
            {voices && page === "script" && <ScriptPanel client={client} voices={voices} onDone={addHistory} />}
            {page === "review" && <ReviewPanel client={client} />}
            {page === "mcp" && <McpPanel client={client} onChange={setMcpOn} />}
            {voices && page === "history" && <HistoryPanel client={client} items={history} onClear={() => setHistory([])} />}
          </div>
        </main>
      </div>
    </ToastProvider>
  );
}
