import type {
  ExportResult, JobInfo, McpClientId, McpClientStatus, McpHttpStatus, McpStatus, ReviewItem, ReviewSummary, SpeechRequest, StudioClient, ValidationReport, VoiceSummary,
} from "./types";
import { WorkerError } from "./types";

interface WorkerFailure {
  type: string;
  message: string;
  controls?: string[];
}

type Invoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

/** Calls the Rust `worker_call` command, which forwards to the Python worker over stdio. */
export function makeTauriClient(invoke: Invoke, saveDialog: (name: string) => Promise<string | null>): StudioClient {
  async function call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    try {
      return await invoke<T>("worker_call", { method, params });
    } catch (err) {
      const e = err as WorkerFailure | string;
      if (typeof e === "string") throw new WorkerError("WorkerUnavailable", e);
      throw new WorkerError(e.type, e.message, e.controls);
    }
  }
  return {
    listVoices: () => call<VoiceSummary[]>("list_voices"),
    generateSpeech: (request: SpeechRequest) => call<JobInfo>("generate_speech", { request }),
    generateDirected: (config: unknown, strict = false) => call<JobInfo>("generate_directed", { config, strict }),
    validate: (config: unknown) => call<ValidationReport>("validate", { config }),
    status: (jobId: string) => call<JobInfo>("status", { job_id: jobId }),
    cancel: (jobId: string) => call<JobInfo>("cancel", { job_id: jobId }),
    audio: async (outputId: string) => {
      const bytes = await invoke<ArrayBuffer | number[]>("read_output_audio", { outputId });
      return bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : Uint8Array.from(bytes);
    },
    mcpStatus: () => call<McpStatus>("mcp_status"),
    mcpHttpStatus: () => call<McpHttpStatus>("mcp_http_status"),
    reviewSummary: (folder?: string) => call<ReviewSummary>("review_summary", folder ? { folder } : {}),
    reviewApprove: (folder: string, file: string, text: string) => call<ReviewItem>("review_approve", { folder, file, text }),
    reviewReject: (folder: string, file: string, rejected: boolean) =>
      call<ReviewItem>("review_reject", { folder, file, rejected }),
    reviewAudio: async (folder: string, file: string) => {
      const bytes = await invoke<ArrayBuffer | number[]>("read_review_audio", { folder, file });
      return bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : Uint8Array.from(bytes);
    },
    mcpHttpSet: (enabled: boolean) => call<McpHttpStatus>(enabled ? "mcp_http_start" : "mcp_http_stop"),
    mcpSetEnabled: (client: McpClientId, enabled: boolean) => call<McpClientStatus>("mcp_set_enabled", { client, enabled }),
    exportWithDialog: async (outputId: string, suggestedName: string) => {
      const path = await saveDialog(suggestedName);
      if (!path) return null;
      return call<ExportResult>("export_to_path", { output_id: outputId, path });
    },
  };
}

export function createClient(): StudioClient {
  // Loaded lazily so tests and a plain browser preview do not need the Tauri runtime.
  const invoke: Invoke = async (cmd, args) => (await import("@tauri-apps/api/core")).invoke(cmd, args);
  const saveDialog = async (name: string) => {
    const { save } = await import("@tauri-apps/plugin-dialog");
    return save({
      defaultPath: `${name}.mp3`,
      filters: [
        { name: "MP3 audio", extensions: ["mp3"] },
        { name: "WAV audio", extensions: ["wav"] },
      ],
    });
  };
  return makeTauriClient(invoke, saveDialog);
}

/** Poll a job until it leaves queued/running. */
export async function waitForJob(
  client: StudioClient,
  job: JobInfo,
  onUpdate: (job: JobInfo) => void,
  intervalMs = 300,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<JobInfo> {
  let current = job;
  onUpdate(current);
  while (current.status === "queued" || current.status === "running") {
    await sleep(intervalMs);
    current = await client.status(current.job_id);
    onUpdate(current);
  }
  return current;
}
