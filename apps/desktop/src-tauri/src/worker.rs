//! Bridge to the Python voice worker (`mvs-worker`): one JSON request per line on stdin,
//! one JSON response per line on stdout. The worker is started on first use and restarted
//! if it exits. Requests are serialised by a mutex because the worker answers in order.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::{Arc, Mutex};

pub struct Worker {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

#[derive(Default, Clone)]
pub struct WorkerState(pub Arc<Mutex<Option<Worker>>>);

const PRESETS: &str = "config/voice_presets.json";

/// Find the repository root (folder containing config/voice_presets.json).
fn find_project_root() -> Option<PathBuf> {
    if let Ok(root) = std::env::var("MVS_PROJECT_ROOT") {
        return Some(PathBuf::from(root));
    }
    let mut starts: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            starts.push(dir.to_path_buf());
        }
    }
    for start in starts {
        let mut dir: Option<&Path> = Some(start.as_path());
        while let Some(d) = dir {
            if d.join(PRESETS).exists() {
                return Some(d.to_path_buf());
            }
            dir = d.parent();
        }
    }
    None
}

fn worker_command() -> Result<Command, String> {
    let root = find_project_root()
        .ok_or("Cannot find the project folder (config/voice_presets.json). Set MVS_PROJECT_ROOT.")?;
    // MVS_WORKER wins; otherwise prefer the GPU environment (adds the own-voice clone),
    // falling back to the CPU environment.
    let exe = match std::env::var("MVS_WORKER") {
        Ok(p) => PathBuf::from(p),
        Err(_) => {
            let (dir, name) = if cfg!(windows) { ("Scripts", "mvs-worker.exe") } else { ("bin", "mvs-worker") };
            [".venv-f5", ".venv-nara"]
                .iter()
                .map(|venv| root.join(venv).join(dir).join(name))
                .find(|p| p.exists())
                .unwrap_or_else(|| root.join(".venv-nara").join(dir).join(name))
        }
    };
    if !exe.exists() {
        return Err(format!("Voice worker not found at {}. Set MVS_WORKER.", exe.display()));
    }
    let mut cmd = Command::new(exe);
    cmd.env("MVS_PROJECT_ROOT", &root)
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    Ok(cmd)
}

fn spawn() -> Result<Worker, String> {
    let mut child = worker_command()?.spawn().map_err(|e| format!("Failed to start voice worker: {e}"))?;
    let stdin = child.stdin.take().ok_or("worker stdin unavailable")?;
    let stdout = BufReader::new(child.stdout.take().ok_or("worker stdout unavailable")?);
    Ok(Worker { child, stdin, stdout, next_id: 1 })
}

impl Worker {
    fn alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    fn call(&mut self, method: &str, params: Value) -> Result<Value, Value> {
        let id = self.next_id;
        self.next_id += 1;
        let line = json!({ "id": id, "method": method, "params": params }).to_string();
        writeln!(self.stdin, "{line}").and_then(|_| self.stdin.flush()).map_err(io_err)?;
        let mut reply = String::new();
        if self.stdout.read_line(&mut reply).map_err(io_err)? == 0 {
            return Err(io_err("voice worker closed its output"));
        }
        let msg: Value = serde_json::from_str(&reply).map_err(|e| io_err(format!("bad worker reply: {e}")))?;
        if msg.get("id").and_then(Value::as_u64) != Some(id) {
            return Err(io_err("worker reply id mismatch"));
        }
        match msg.get("error") {
            Some(err) => Err(err.clone()),
            None => Ok(msg.get("result").cloned().unwrap_or(Value::Null)),
        }
    }
}

fn io_err(e: impl std::fmt::Display) -> Value {
    json!({ "type": "WorkerUnavailable", "message": e.to_string() })
}

/// Send one request, starting (or restarting) the worker if needed.
pub fn call(state: &WorkerState, method: &str, params: Value) -> Result<Value, Value> {
    let mut guard = state.0.lock().map_err(|_| io_err("worker lock poisoned"))?;
    if !guard.as_mut().map(Worker::alive).unwrap_or(false) {
        *guard = Some(spawn().map_err(io_err)?);
    }
    let worker = guard.as_mut().expect("worker present");
    let result = worker.call(method, params);
    if let Err(e) = &result {
        if e.get("type").and_then(Value::as_str) == Some("WorkerUnavailable") {
            *guard = None; // force a clean restart on the next call
        }
    }
    result
}

impl Drop for Worker {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Talks to the real Python worker (needs .venv-nara with mvs-worker installed).
    #[test]
    fn real_worker_round_trip() {
        let state = WorkerState::default();
        let pong = call(&state, "ping", json!({})).expect("ping");
        assert_eq!(pong["ok"], json!(true));
        let voices = call(&state, "list_voices", json!({})).expect("voices");
        let ids: Vec<&str> = voices.as_array().unwrap().iter().filter_map(|v| v["voice_id"].as_str()).collect();
        assert!(ids.contains(&"male_calm"));
        let err = call(&state, "capabilities", json!({"voice_id": "nobody"})).unwrap_err();
        assert_eq!(err["type"], json!("ValueError"));
        let job = call(&state, "generate_speech", json!({"request": {"text": "မင်္ဂလာပါ", "voice_id": "male_calm"}}))
            .expect("job");
        let id = job["job_id"].as_str().unwrap().to_string();
        let mut status = Value::Null;
        for _ in 0..300 {
            status = call(&state, "status", json!({"job_id": id})).unwrap();
            if status["status"] != json!("queued") && status["status"] != json!("running") {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        assert_eq!(status["status"], json!("completed"), "{status}");
        let path = call(&state, "audio_path", json!({"output_id": id})).unwrap();
        assert!(std::fs::metadata(path.as_str().unwrap()).unwrap().len() > 1000);
    }
}
