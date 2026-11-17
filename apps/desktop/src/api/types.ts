// Types mirroring the Python worker results (src/myanmar_voice_studio/engine/schemas.py,
// mcp_server/service.py). The voice-direction document type is generated from the JSON
// Schema: run `npm run gen:types` after changing schemas/voice-direction-1.0.json.
export type { VoiceDirection } from "./voice-direction";

export type Support = "native" | "dsp" | "engine" | "unsupported";

export interface VoiceSummary {
  voice_id: string;
  display_name: string;
  adapter_id: string;
  speaker: string;
  supported_controls: Record<string, Support>;
  /** For enum controls: the values that can actually be applied. */
  control_values?: Record<string, string[]>;
  note: string;
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface JobInfo {
  job_id: string;
  kind: "speech" | "directed";
  status: JobStatus;
  progress: number;
  output_id: string | null;
  duration_s: number | null;
  unsupported: string[];
  warnings: string[];
  error: string | null;
}

export interface SpeechRequest {
  text: string;
  voice_id: string;
  speed?: number;
  pitch_semitones?: number;
  emotion?: string | null;
  delivery?: string | null;
  pause_after_ms?: number;
  strict?: boolean;
}

export interface ValidationReport {
  valid: boolean;
  errors: string[];
  unsupported: string[];
  warnings: string[];
}

export interface ExportResult {
  output_id: string;
  path: string;
  format: string;
  bytes: number;
}

export class WorkerError extends Error {
  constructor(
    public readonly type: string,
    message: string,
    public readonly controls?: string[],
  ) {
    super(message);
    this.name = "WorkerError";
  }
}

export type McpClientId = "claude_desktop" | "claude_code";

export interface McpClientStatus {
  client: McpClientId;
  label: string;
  enabled: boolean;
  config_path: string;
  config_exists: boolean;
  error: string | null;
  restart_note: string;
}

export interface McpStatus {
  server_command: string;
  server_available: boolean;
  clients: McpClientStatus[];
}

export interface McpHttpStatus {
  running: boolean;
  url: string;
  port: number;
  tools: string[];
  claude_code_command: string;
  codex_command: string;
  error: string | null;
}

export type ReviewStatus = "approved" | "draft" | "rejected" | "missing";

export interface ReviewItem {
  file: string;
  status: ReviewStatus;
  text: string;
  heard: string;
  script_id: string | null;
  script_text: string;
  ser: number | null;
  duration_s: number;
}

export interface ReviewSummary {
  folder: string;
  folders: string[];
  items: ReviewItem[];
  approved: number;
  draft: number;
  rejected: number;
  approved_minutes: number;
}

/** Everything the UI needs from the voice engine. Implemented over Tauri, mocked in tests. */
export interface StudioClient {
  listVoices(): Promise<VoiceSummary[]>;
  generateSpeech(request: SpeechRequest): Promise<JobInfo>;
  generateDirected(config: unknown, strict?: boolean): Promise<JobInfo>;
  validate(config: unknown): Promise<ValidationReport>;
  status(jobId: string): Promise<JobInfo>;
  cancel(jobId: string): Promise<JobInfo>;
  /** Audio bytes of a finished output, for playback. */
  audio(outputId: string): Promise<Uint8Array>;
  /** Ask the user where to save, then export. Returns null if the user cancelled the dialog. */
  exportWithDialog(outputId: string, suggestedName: string): Promise<ExportResult | null>;
  /** Which AI clients have the MCP server registered (= "on"). */
  mcpStatus(): Promise<McpStatus>;
  mcpSetEnabled(client: McpClientId, enabled: boolean): Promise<McpClientStatus>;
  /** Local HTTP MCP endpoint that lives while the app is open. */
  mcpHttpStatus(): Promise<McpHttpStatus>;
  mcpHttpSet(enabled: boolean): Promise<McpHttpStatus>;
  /** Own-voice transcript review. */
  reviewSummary(folder?: string): Promise<ReviewSummary>;
  reviewAudio(folder: string, file: string): Promise<Uint8Array>;
  reviewApprove(folder: string, file: string, text: string): Promise<ReviewItem>;
  reviewReject(folder: string, file: string, rejected: boolean): Promise<ReviewItem>;
}
