mod worker;

use serde_json::Value;
use tauri::ipc::Response;
use tauri::State;
use worker::WorkerState;

/// Forward a request to the Python voice worker. Errors keep the worker's {type, message} shape.
#[tauri::command]
async fn worker_call(state: State<'_, WorkerState>, method: String, params: Value) -> Result<Value, Value> {
    // The worker does blocking I/O; keep it off the UI thread.
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || worker::call(&state, &method, params))
    .await
    .map_err(|e| serde_json::json!({ "type": "WorkerUnavailable", "message": e.to_string() }))?
}

/// Return the audio bytes of a finished output for playback. Paths never reach the UI.
#[tauri::command]
async fn read_output_audio(state: State<'_, WorkerState>, output_id: String) -> Result<Response, Value> {
    let path = worker_call(state, "audio_path".into(), serde_json::json!({ "output_id": output_id })).await?;
    let path = path.as_str().ok_or_else(|| serde_json::json!({"type": "ValueError", "message": "no audio path"}))?;
    let bytes = std::fs::read(path)
        .map_err(|e| serde_json::json!({ "type": "IOError", "message": e.to_string() }))?;
    Ok(Response::new(bytes))
}

/// Audio bytes of one recording for the Review screen. The worker validates folder/file
/// (confined to <project>/recordings/<folder>/<name>.wav) before any path is read here.
#[tauri::command]
async fn read_review_audio(state: State<'_, WorkerState>, folder: String, file: String) -> Result<Response, Value> {
    let path = worker_call(state, "review_audio_path".into(), serde_json::json!({ "folder": folder, "file": file })).await?;
    let path = path.as_str().ok_or_else(|| serde_json::json!({"type": "ValueError", "message": "no audio path"}))?;
    let bytes = std::fs::read(path)
        .map_err(|e| serde_json::json!({ "type": "IOError", "message": e.to_string() }))?;
    Ok(Response::new(bytes))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(WorkerState::default())
        .invoke_handler(tauri::generate_handler![worker_call, read_output_audio, read_review_audio])
        .run(tauri::generate_context!())
        .expect("error while running Myanmar Voice Studio");
}
