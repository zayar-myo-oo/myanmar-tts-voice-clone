import { useEffect, useState } from "react";
import type { McpClientId, McpHttpStatus, McpStatus, StudioClient } from "../api/types";
import { Icon, useToast } from "./shared";

const AUTO_KEY = "mvs.mcp.http.enabled";
const remember = (on: boolean) => { try { localStorage.setItem(AUTO_KEY, on ? "1" : "0"); } catch { /* storage unavailable */ } };
export const rememberedHttpOn = () => { try { return localStorage.getItem(AUTO_KEY) === "1"; } catch { return false; } };

export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full border transition disabled:opacity-40 ${on ? "border-emerald-400 bg-emerald-500" : "border-white/20 bg-white/10"}`}>
      <span className={`absolute top-[3px] h-5 w-5 rounded-full shadow transition-all ${on ? "left-6 bg-white" : "left-1 bg-slate-400"}`} />
    </button>
  );
}

function CopyRow({ text, label }: { text: string; label: string }) {
  const toast = useToast();
  return (
    <button aria-label={label} title={text}
      onClick={() => navigator.clipboard.writeText(text).then(() => toast("ok", `Copied: ${label}`), () => toast("error", "Copy မရပါ"))}
      className="inline-flex items-center gap-2 rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-40">
      <Icon name="script" className="h-3.5 w-3.5" />{label}
    </button>
  );
}

export function McpPanel({ client, onChange }: { client: StudioClient; onChange?: (on: boolean) => void }) {
  const toast = useToast();
  const [http, setHttp] = useState<McpHttpStatus | null>(null);
  const [stdio, setStdio] = useState<McpStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);

  useEffect(() => {
    client.mcpHttpStatus().then((s) => { setHttp(s); onChange?.(s.running); }).catch((e: Error) => setError(e.message));
    client.mcpStatus().then(setStdio).catch(() => setStdio(null));
  }, [client, onChange]);

  async function toggleHttp(on: boolean) {
    setBusy(true);
    try {
      const s = await client.mcpHttpSet(on);
      setHttp(s);
      remember(on);
      onChange?.(s.running);
      toast("ok", on ? `MCP ဖွင့်ပြီး: ${s.url}` : "MCP ပိတ်ပြီး");
    } catch (e) {
      toast("error", `MCP ${on ? "ဖွင့်" : "ပိတ်"}လို့ မရပါ: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function toggleStdio(id: McpClientId, on: boolean) {
    try {
      const updated = await client.mcpSetEnabled(id, on);
      setStdio(await client.mcpStatus());
      toast("ok", `${updated.label}: ${on ? "ON" : "OFF"} — ${updated.restart_note}`);
    } catch (e) {
      toast("error", (e as Error).message);
    }
  }

  const on = http?.running ?? false;
  return (
    <div className="max-w-3xl space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Connections</h1>
        <p className="mt-1 text-sm text-slate-400">AI tool တွေကို ဒီ app ရဲ့ မြန်မာအသံနဲ့ ပြောခိုင်းပါ။ Let your tools speak through Voice Studio.</p>
      </header>
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}

      <section className="flex items-center justify-between rounded-2xl bg-white/[0.04] px-5 py-4">
        <div>
          <p className="font-medium">Enable MCP connection</p>
          <p className="text-xs text-slate-400">Windows · This device only (127.0.0.1)</p>
        </div>
        <Switch label="Enable MCP connection" on={on} disabled={!http || busy} onChange={toggleHttp} />
      </section>

      {http && (
        <>
          <ul className="space-y-2 pl-1" aria-label="tools">
            {http.tools.map((t) => (
              <li key={t} className={`flex items-center gap-3 text-sm ${on ? "text-slate-200" : "text-slate-500"}`}>
                <Icon name="check" className={`h-4 w-4 ${on ? "text-emerald-400" : "text-slate-600"}`} />
                <code>{t}</code>
              </li>
            ))}
          </ul>

          <div className="space-y-3">
            <p className="text-sm text-slate-300">ဒီ link ကို AI tool ရဲ့ MCP server URL နေရာမှာ ထည့်ပါ။ သုံးနေစဉ် ဒီ app ကို ဖွင့်ထားပါ။</p>
            <div className={`flex items-center justify-between rounded-2xl px-5 py-4 ${on ? "bg-slate-100 text-slate-900" : "bg-white/[0.04] text-slate-500"}`}>
              <code data-testid="mcp-url" className="text-sm">{http.url}</code>
              <button aria-label="copy url" disabled={!on}
                onClick={() => navigator.clipboard.writeText(http.url).then(() => toast("ok", "URL copied"))}
                className="rounded p-1 hover:bg-black/10 disabled:opacity-40">
                <Icon name="script" className="h-4 w-4" />
              </button>
            </div>
            <div className={`flex flex-wrap gap-2 ${on ? "" : "pointer-events-none opacity-40"}`}>
              <CopyRow text={http.codex_command} label="Copy Codex command" />
              <CopyRow text={http.claude_code_command} label="Copy Claude Code command" />
            </div>
            {http.error && <p className="text-xs text-rose-300">{http.error}</p>}
          </div>
        </>
      )}

      <section className="border-t border-white/5 pt-4">
        <button className="text-sm text-slate-400 hover:text-slate-200" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
          {advanced ? "▾" : "▸"} Advanced — app မဖွင့်ထားလည်း သုံးချင်ရင် (stdio)
        </button>
        {advanced && stdio && (
          <ul className="mt-3 space-y-2">
            {stdio.clients.map((c) => (
              <li key={c.client} className="flex items-center gap-4 rounded-xl bg-white/[0.03] px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{c.label}</p>
                  <p className="truncate text-xs text-slate-500" title={c.config_path}>{c.config_path}</p>
                  {c.error && <p className="text-xs text-rose-300">{c.error}</p>}
                </div>
                <Switch label={`stdio ${c.label}`} on={c.enabled} disabled={!!c.error || !stdio.server_available}
                  onChange={(v) => toggleStdio(c.client, v)} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
