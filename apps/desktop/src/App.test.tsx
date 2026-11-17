import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { makeTauriClient, waitForJob } from "./api/client";
import type { JobInfo, StudioClient, VoiceSummary } from "./api/types";
import { WorkerError } from "./api/types";

const VOICES: VoiceSummary[] = [
  {
    voice_id: "male_calm",
    display_name: "Male — Calm Narrator",
    adapter_id: "nara-mini-v1",
    speaker: "htet-myat",
    supported_controls: { speed: "dsp", pitch: "dsp", pause_after: "engine", emotion: "unsupported", delivery: "unsupported" },
    note: "Target profile.",
  },
];

function job(over: Partial<JobInfo> = {}): JobInfo {
  return { job_id: "j1", kind: "speech", status: "queued", progress: 0, output_id: null, duration_s: null,
    unsupported: [], warnings: [], error: null, ...over };
}

let mcpOn = false;
let reviewApproved = false;

function mockClient(over: Partial<StudioClient> = {}): StudioClient {
  return {
    listVoices: vi.fn().mockResolvedValue(VOICES),
    generateSpeech: vi.fn().mockResolvedValue(job()),
    generateDirected: vi.fn().mockResolvedValue(job({ kind: "directed" })),
    validate: vi.fn().mockResolvedValue({ valid: true, errors: [], unsupported: ["segment_001: emotion=curious"], warnings: [] }),
    status: vi.fn().mockResolvedValue(
      job({ status: "completed", progress: 1, output_id: "j1", duration_s: 2.5, unsupported: ["emotion=sad"] }),
    ),
    cancel: vi.fn().mockResolvedValue(job({ status: "cancelled" })),
    audio: vi.fn().mockResolvedValue(new Uint8Array([82, 73, 70, 70])),
    exportWithDialog: vi.fn().mockResolvedValue({ output_id: "j1", path: "C:/x/a.mp3", format: "mp3", bytes: 10 }),
    mcpStatus: vi.fn().mockImplementation(async () => ({
      server_command: "mvs-mcp.exe", server_available: true,
      clients: [{ client: "claude_desktop", label: "Claude Desktop", enabled: mcpOn, config_path: "cfg.json",
        config_exists: true, error: null, restart_note: "restart Claude" }],
    })),
    mcpHttpStatus: vi.fn().mockResolvedValue({ running: false, url: "http://127.0.0.1:17863/mcp", port: 17863, error: null,
      tools: [], claude_code_command: "", codex_command: "" }),
    mcpHttpSet: vi.fn(),
    reviewSummary: vi.fn().mockImplementation(async () => ({ folder: "take", folders: ["take"], approved: reviewApproved ? 1 : 0,
      draft: reviewApproved ? 0 : 1, rejected: 0, approved_minutes: reviewApproved ? 0.05 : 0,
      items: [{ file: "nr026.wav", status: reviewApproved ? "approved" : "draft", text: reviewApproved ? "ဒီနေ့ ရာသီဥတု အရမ်း လှပပါတယ်။" : "ဒီနေ့ရာသီဥတုအရမ်းလှတယ်",
        heard: "ဒီနေ့ရာသီဥတုအရမ်းလှတယ်", script_id: "r002", script_text: "ဒီနေ့ ရာသီဥတု အရမ်း လှပပါတယ်။", ser: 0.167, duration_s: 3.2 }] })),
    reviewAudio: vi.fn().mockResolvedValue(new Uint8Array([82, 73, 70, 70])),
    reviewApprove: vi.fn().mockImplementation(async (_f: string, file: string, text: string) => {
      reviewApproved = true;
      return { file, status: "approved", text, heard: "", script_id: "r002", script_text: "", ser: 0, duration_s: 3.2 };
    }),
    reviewReject: vi.fn(),
    mcpSetEnabled: vi.fn().mockImplementation(async (_c: string, on: boolean) => {
      mcpOn = on;
      return { client: "claude_desktop", label: "Claude Desktop", enabled: on, config_path: "cfg.json",
        config_exists: true, error: null, restart_note: "restart Claude" };
    }),
    ...over,
  };
}

beforeAll(() => {
  // jsdom has no object URLs
  globalThis.URL.createObjectURL = vi.fn(() => "blob:test");
  globalThis.URL.revokeObjectURL = vi.fn();
});

test("draft survives remount and clearing can be undone", async () => {
  const saved = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value),
  });
  try {
    const first = render(<App client={mockClient()} />);
    await screen.findByRole("textbox", { name: "text" });
    fireEvent.change(screen.getByRole("textbox", { name: "text" }), { target: { value: "ကိုယ်ပိုင် စာမူ" } });
    first.unmount();
    render(<App client={mockClient()} />);
    expect(await screen.findByRole("textbox", { name: "text" })).toHaveValue("ကိုယ်ပိုင် စာမူ");
    fireEvent.click(screen.getByRole("button", { name: "ရှင်းမယ်" }));
    expect(screen.getByRole("textbox", { name: "text" })).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "မူလစာ ပြန်ယူမယ်" }));
    expect(screen.getByRole("textbox", { name: "text" })).toHaveValue("ကိုယ်ပိုင် စာမူ");
  } finally { vi.unstubAllGlobals(); }
});

test("shows capability badges so unsupported controls are visible before generating", async () => {
  render(<App client={mockClient()} />);
  expect(await screen.findByRole("radio", { name: /Calm Narrator/ })).toHaveAttribute("aria-checked", "true");
  expect(screen.getAllByText("DSP")).toHaveLength(2);
  expect(screen.getAllByText("မရပါ")).toHaveLength(2);
});

test("generate → poll → player, export, and unsupported warning", async () => {
  const client = mockClient();
  render(<App client={client} />);
  await screen.findByRole("radio", { name: /Calm Narrator/ });
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "emotion" }), "sad");
  fireEvent.click(screen.getByRole("button", { name: "အသံထုတ်မယ်" }));
  expect(await screen.findByTestId("player")).toBeInTheDocument();
  expect(client.generateSpeech).toHaveBeenCalledWith(expect.objectContaining({ voice_id: "male_calm", emotion: "sad" }));
  expect(screen.getByTestId("job-status")).toHaveTextContent("completed");
  expect(screen.getByRole("alert")).toHaveTextContent("emotion=sad");
  fireEvent.click(screen.getByRole("button", { name: /Export/ }));
  expect(await screen.findByText(/C:\/x\/a.mp3/)).toBeInTheDocument(); // toast
  fireEvent.click(screen.getByRole("button", { name: /History/ }));
  expect(await screen.findByText("ကမ္ဘာကြီးက တည်ရှိနေတာ ကြာပြီ။")).toBeInTheDocument();
});

test("strict-mode refusal is shown as an error", async () => {
  const client = mockClient({
    generateSpeech: vi.fn().mockRejectedValue(new WorkerError("UnsupportedControlError", "delivery=whisper", ["delivery=whisper"])),
  });
  render(<App client={client} />);
  await screen.findByRole("radio", { name: /Calm Narrator/ });
  fireEvent.click(screen.getByRole("button", { name: "အသံထုတ်မယ်" }));
  expect(await screen.findByText(/Strict mode — ထုတ်မပေးပါ: delivery=whisper/)).toBeInTheDocument();
});

test("worker unavailable shows a helpful message", async () => {
  render(<App client={mockClient({ listVoices: vi.fn().mockRejectedValue(new Error("spawn failed")) })} />);
  expect(await screen.findByText(/ချိတ်လို့ မရပါ/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "ပြန်ချိတ်မယ်" })).toBeInTheDocument();
  expect(screen.getByText("spawn failed")).toBeInTheDocument();
});

test("script tab validates and lists unsupported controls", async () => {
  render(<App client={mockClient()} />);
  await screen.findByRole("radio", { name: /Calm Narrator/ });
  fireEvent.click(screen.getByRole("button", { name: /Voice Direction/ }));
  expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3 segments
  fireEvent.click(screen.getByRole("button", { name: /Validate/ }));
  await waitFor(() => expect(screen.getByTestId("report")).toHaveTextContent("Valid · 3 segments"));
  expect(screen.getByText("emotion=curious ✗")).toBeInTheDocument();
});

test("script tab reports invalid JSON without calling the worker", async () => {
  const client = mockClient();
  render(<App client={client} />);
  await screen.findByRole("radio", { name: /Calm Narrator/ });
  fireEvent.click(screen.getByRole("button", { name: /Voice Direction/ }));
  fireEvent.click(screen.getByRole("tab", { name: "JSON" }));
  fireEvent.change(screen.getByRole("textbox", { name: "script-json" }), { target: { value: "{oops" } });
  fireEvent.click(screen.getByRole("button", { name: /Validate/ }));
  expect(await screen.findByText(/JSON မမှန်ပါ/)).toBeInTheDocument();
  expect(screen.getByText(/JSON error/)).toBeInTheDocument();
  expect(client.validate).not.toHaveBeenCalled();
});

test("waitForJob polls until a final state", async () => {
  const states = [job({ status: "running", progress: 0.5 }), job({ status: "completed", progress: 1, output_id: "j1" })];
  const client = mockClient({ status: vi.fn().mockImplementation(async () => states.shift()) });
  const seen: string[] = [];
  const final = await waitForJob(client, job(), (j) => seen.push(j.status), 0, async () => {});
  expect(final.status).toBe("completed");
  expect(seen).toEqual(["queued", "running", "completed"]);
});

test("tauri client maps worker errors to WorkerError", async () => {
  const invoke = vi.fn().mockRejectedValue({ type: "ValueError", message: "Unknown voice 'x'" });
  const client = makeTauriClient(invoke as never, async () => null);
  await expect(client.listVoices()).rejects.toMatchObject({ type: "ValueError", message: "Unknown voice 'x'" });
  expect(await client.exportWithDialog("j1", "a")).toBeNull(); // dialog cancelled → nothing exported
});

test("Connections page: MCP switch starts the local endpoint and enables copy buttons", async () => {
  mcpOn = false;
  let running = false;
  const status = () => ({ running, url: "http://127.0.0.1:17863/mcp", port: 17863, error: null, tools: ["list_voices", "generate_speech"],
    claude_code_command: "claude mcp add --transport http myanmar-voice-studio http://127.0.0.1:17863/mcp",
    codex_command: "codex mcp add myanmar-voice-studio --url http://127.0.0.1:17863/mcp" });
  const client = mockClient({
    mcpHttpStatus: vi.fn().mockImplementation(async () => status()),
    mcpHttpSet: vi.fn().mockImplementation(async (on: boolean) => { running = on; return status(); }),
  });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  render(<App client={client} />);
  expect(await screen.findByTestId("mcp-badge")).toHaveTextContent("OFF");
  fireEvent.click(screen.getByRole("button", { name: /Connections/ }));
  const sw = await screen.findByRole("switch", { name: "Enable MCP connection" });
  expect(screen.getByTestId("mcp-url")).toHaveTextContent("http://127.0.0.1:17863/mcp");
  expect(screen.getByRole("button", { name: "copy url" })).toBeDisabled();
  fireEvent.click(sw);
  await waitFor(() => expect(screen.getByRole("switch", { name: "Enable MCP connection" })).toHaveAttribute("aria-checked", "true"));
  expect(client.mcpHttpSet).toHaveBeenCalledWith(true);
  expect(screen.getByTestId("mcp-badge")).toHaveTextContent("ON");
  fireEvent.click(screen.getByRole("button", { name: "Copy Claude Code command" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("claude mcp add --transport http")));
  fireEvent.click(screen.getByRole("switch", { name: "Enable MCP connection" }));
  await waitFor(() => expect(screen.getByTestId("mcp-badge")).toHaveTextContent("OFF"));
});

test("Review: listen, use script text, approve updates counts", async () => {
  reviewApproved = false;
  const client = mockClient();
  render(<App client={client} />);
  await screen.findByRole("radio", { name: /Narrator/ });
  fireEvent.click(screen.getByRole("button", { name: /Own-voice review/ }));
  expect(await screen.findByTestId("review-audio")).toBeInTheDocument();
  expect(client.reviewAudio).toHaveBeenCalledWith("take", "nr026.wav");
  const box = screen.getByRole("textbox", { name: "transcript" });
  expect(box).toHaveValue("ဒီနေ့ရာသီဥတုအရမ်းလှတယ်");
  fireEvent.click(screen.getByRole("button", { name: "Script စာ သုံး" }));
  expect(box).toHaveValue("ဒီနေ့ ရာသီဥတု အရမ်း လှပပါတယ်။");
  fireEvent.click(screen.getByRole("button", { name: /အတည်ပြု$/ }));
  await waitFor(() => expect(client.reviewApprove).toHaveBeenCalledWith("take", "nr026.wav", "ဒီနေ့ ရာသီဥတု အရမ်း လှပပါတယ်။"));
  await waitFor(() => expect(screen.getByTestId("review-counts")).toHaveTextContent("အတည်ပြု 1"));
});
