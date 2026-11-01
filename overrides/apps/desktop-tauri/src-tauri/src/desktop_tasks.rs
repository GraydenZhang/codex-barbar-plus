use std::{
    collections::{HashMap, HashSet},
    fs::{self, File},
    io::{self, BufRead, BufReader, Read, Seek, SeekFrom},
    path::{Path, PathBuf},
    sync::Mutex,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use chrono::{DateTime, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};
use uuid::Uuid;

use crate::state::AppState;

const EVENT_NAME: &str = "desktop-task-state-changed";
const MAX_VISIBLE_TASKS: usize = 8;
const MAX_BOOTSTRAP_BYTES: u64 = 768 * 1024;
const RECOVERY_BLOCK_BYTES: u64 = 64 * 1024;
const TAIL_RECONCILE_BYTES: u64 = 160 * 1024;
const DISCOVERY_INTERVAL_TICKS: u64 = 4;
const POLL_INTERVAL: Duration = Duration::from_millis(500);
const COMPLETION_SOUND_MINIMUM: Duration = Duration::from_secs(3 * 60);
const RECENT_FILE_WINDOW: Duration = Duration::from_secs(15);
const RECENT_TERMINAL_TASK_WINDOW: Duration = Duration::from_secs(15 * 60);

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DesktopTaskDto {
    pub id: String,
    pub thread_id: String,
    pub title: String,
    pub status: String,
    pub started_at: String,
    pub finished_at: Option<String>,
    pub duration_seconds: Option<u64>,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DesktopTaskSnapshotDto {
    pub tasks: Vec<DesktopTaskDto>,
    pub updated_at: Option<String>,
}

#[derive(Default)]
pub struct DesktopTaskStore {
    snapshot: Mutex<DesktopTaskSnapshotDto>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TaskStatus {
    Working,
    Completed,
    Error,
}

#[derive(Debug, Clone)]
struct TaskRecord {
    turn_id: String,
    thread_id: String,
    title: String,
    status: TaskStatus,
    started_at: DateTime<Utc>,
    finished_at: Option<DateTime<Utc>>,
    duration: Option<Duration>,
}

#[derive(Default)]
struct RuntimeState {
    tasks: HashMap<String, TaskRecord>,
    active_turn_by_thread: HashMap<String, String>,
    thread_titles: HashMap<String, String>,
    indexed_title_threads: HashSet<String>,
    thread_id_by_file: HashMap<PathBuf, String>,
    ignored_files: HashSet<PathBuf>,
    file_offsets: HashMap<PathBuf, u64>,
    known_files: HashSet<PathBuf>,
    notified_turns: HashSet<String>,
    tick: u64,
}

#[tauri::command]
pub fn get_desktop_task_snapshot(
    store: tauri::State<'_, DesktopTaskStore>,
) -> Result<DesktopTaskSnapshotDto, String> {
    store
        .snapshot
        .lock()
        .map(|snapshot| snapshot.clone())
        .map_err(|error| error.to_string())
}

pub fn start(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let codex_root = codex_root();
        let sessions_root = codex_root.join("sessions");
        let session_index = codex_root.join("session_index.jsonl");
        let mut runtime = RuntimeState::default();

        loop {
            runtime.tick = runtime.tick.wrapping_add(1);
            if runtime.tick == 1 || runtime.tick % DISCOVERY_INTERVAL_TICKS == 0 {
                let index_titles = read_session_index_titles(&session_index);
                for (thread_id, title) in index_titles {
                    runtime
                        .thread_titles
                        .insert(thread_id.clone(), title.clone());
                    runtime.indexed_title_threads.insert(thread_id.clone());
                    for task in runtime.tasks.values_mut() {
                        if task.thread_id == thread_id {
                            task.title = title.clone();
                        }
                    }
                }
                discover_session_files(&sessions_root, &mut runtime);
            }
            process_known_files(&app, &mut runtime);
            reconcile_active_turns(&mut runtime);
            prune_tasks(&mut runtime);
            publish_snapshot(&app, &runtime);
            tokio::time::sleep(POLL_INTERVAL).await;
        }
    });
}

fn codex_root() -> PathBuf {
    if let Some(value) = std::env::var_os("CODEX_HOME") {
        return PathBuf::from(value);
    }
    if let Some(value) = std::env::var_os("USERPROFILE") {
        return PathBuf::from(value).join(".codex");
    }
    if let Some(value) = std::env::var_os("HOME") {
        return PathBuf::from(value).join(".codex");
    }
    PathBuf::from(".codex")
}

fn discover_session_files(root: &Path, runtime: &mut RuntimeState) {
    let mut files = Vec::new();
    collect_jsonl(root, 0, &mut files);
    files.sort_by(|left, right| right.0.cmp(&left.0));

    for (_, path) in files.into_iter().take(64) {
        if runtime.known_files.insert(path.clone()) {
            bootstrap_file(runtime, &path);
        }
    }
}

fn collect_jsonl(root: &Path, depth: usize, output: &mut Vec<(SystemTime, PathBuf)>) {
    if depth > 6 {
        return;
    }
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        if file_type.is_dir() {
            collect_jsonl(&path, depth + 1, output);
            continue;
        }
        if path.extension().and_then(|value| value.to_str()) != Some("jsonl") {
            continue;
        }
        let modified = entry
            .metadata()
            .and_then(|metadata| metadata.modified())
            .unwrap_or(UNIX_EPOCH);
        output.push((modified, path));
    }
}

fn read_session_index_titles(path: &Path) -> HashMap<String, String> {
    let Ok(file) = File::open(path) else {
        return HashMap::new();
    };
    let reader = BufReader::new(file);
    let mut titles = HashMap::new();
    for line in reader.lines().map_while(Result::ok) {
        let Ok(value) = serde_json::from_str::<Value>(&line) else {
            continue;
        };
        let Some(thread_id) = value.get("id").and_then(Value::as_str).or_else(|| {
            value
                .get("thread_id")
                .and_then(Value::as_str)
                .or_else(|| value.get("threadId").and_then(Value::as_str))
        }) else {
            continue;
        };
        let title = value
            .get("thread_name")
            .and_then(Value::as_str)
            .or_else(|| value.get("title").and_then(Value::as_str))
            .and_then(clean_title);
        if let Some(title) = title {
            titles.insert(thread_id.to_string(), title);
        }
    }
    titles
}

fn bootstrap_file(runtime: &mut RuntimeState, path: &Path) {
    let thread_id = match read_session_metadata(path) {
        SessionMetadata::Ready(thread_id) => thread_id,
        SessionMetadata::Pending => return,
        SessionMetadata::Ignored => {
            runtime.ignored_files.insert(path.to_path_buf());
            return;
        }
    };
    let Ok(mut file) = File::open(path) else {
        return;
    };
    let Ok(metadata) = file.metadata() else {
        return;
    };
    let len = metadata.len();
    let start = len.saturating_sub(MAX_BOOTSTRAP_BYTES);
    let mut tail = vec![0; (len - start) as usize];
    if file.seek(SeekFrom::Start(start)).is_err() || file.read_exact(&mut tail).is_err() {
        return;
    }
    let last_newline = tail.iter().rposition(|byte| *byte == b'\n');
    let first_complete = if start == 0 {
        0
    } else {
        tail.iter()
            .position(|byte| *byte == b'\n')
            .map_or(tail.len(), |position| position + 1)
    };
    let tail_end = last_newline.map_or(0, |position| position + 1);
    let lines = &tail[first_complete.min(tail_end)..tail_end];
    let has_lifecycle = lines
        .split(|byte| *byte == b'\n')
        .filter_map(|line| std::str::from_utf8(line).ok())
        .any(|line| lifecycle_event(line).is_some());
    // A long turn can have megabytes of output after its start. Only on
    // bootstrap, and only without lifecycle evidence in the bounded tail,
    // search further back. The first lifecycle found is authoritative: a
    // completion/error must never resurrect an older start.
    let recovery = if has_lifecycle {
        None
    } else {
        let Ok(recovery) = recover_latest_lifecycle(&mut file, len) else {
            return;
        };
        Some(recovery)
    };
    runtime
        .thread_id_by_file
        .insert(path.to_path_buf(), thread_id.clone());
    for line in lines
        .split(|byte| *byte == b'\n')
        .filter_map(|line| std::str::from_utf8(line).ok())
    {
        process_line(runtime, path, line, false, None);
    }
    if let Some((Some(event), _)) = &recovery
        && event.status == TaskStatus::Working
    {
        start_task(runtime, &thread_id, &event.turn_id, event.started_at);
    }
    let committed_end = recovery.map_or_else(
        || start + tail_end as u64,
        |(_, committed_end)| committed_end,
    );
    runtime.file_offsets.insert(path.to_path_buf(), committed_end);
    prune_tasks(runtime);
}

fn process_known_files(app: &AppHandle, runtime: &mut RuntimeState) {
    let paths: Vec<PathBuf> = runtime.known_files.iter().cloned().collect();
    for path in paths {
        process_file_updates(runtime, &path, Some(app));
    }
}

fn process_file_updates(runtime: &mut RuntimeState, path: &Path, app: Option<&AppHandle>) {
    if runtime.ignored_files.contains(path) {
        return;
    }
    // A newly discovered file may still be empty, half-written or locked.
    // Retry its metadata before accepting any events (including subagent events).
    let Some(&offset) = runtime.file_offsets.get(path) else {
        bootstrap_file(runtime, path);
        return;
    };
    let Ok(mut file) = File::open(path) else {
        return;
    };
    let Ok(metadata) = file.metadata() else {
        return;
    };
    let len = metadata.len();
    if len < offset {
        runtime.file_offsets.remove(path);
        bootstrap_file(runtime, path);
        return;
    }
    if file.seek(SeekFrom::Start(offset)).is_err() {
        return;
    }
    let mut reader = BufReader::new(file.take(len - offset));
    let mut line = String::new();
    let mut position = offset;
    loop {
        line.clear();
        let Ok(read) = reader.read_line(&mut line) else {
            break;
        };
        if read == 0 || !line.ends_with('\n') {
            // Keep the offset before an unfinished JSONL record so the next
            // poll can consume the complete event after the writer appends it.
            break;
        }
        position = position.saturating_add(read as u64);
        process_line(runtime, path, line.trim_end(), true, app);
    }
    runtime.file_offsets.insert(path.to_path_buf(), position);
}

#[derive(Deserialize)]
struct LifecycleProjection {
    #[serde(rename = "type")]
    kind: Option<String>,
    timestamp: Option<Value>,
    payload: Option<LifecyclePayload>,
}

#[derive(Deserialize)]
struct LifecyclePayload {
    #[serde(rename = "type")]
    kind: Option<String>,
    turn_id: Option<String>,
    started_at: Option<Value>,
}

struct RecoveredLifecycle {
    turn_id: String,
    status: TaskStatus,
    started_at: DateTime<Utc>,
}

impl LifecycleProjection {
    fn into_lifecycle(self) -> Option<RecoveredLifecycle> {
        if self.kind.as_deref() != Some("event_msg") {
            return None;
        }
        let payload = self.payload?;
        let status = match payload.kind.as_deref()? {
            "task_started" => TaskStatus::Working,
            "task_complete" | "turn_completed" => TaskStatus::Completed,
            "turn_aborted" | "turn_failed" | "task_failed" => TaskStatus::Error,
            _ => return None,
        };
        let started_at = payload
            .started_at
            .and_then(|value| value.as_i64())
            .and_then(|seconds| Utc.timestamp_opt(seconds, 0).single())
            .or_else(|| parse_timestamp(self.timestamp.as_ref()))
            .unwrap_or_else(Utc::now);
        Some(RecoveredLifecycle {
            turn_id: payload.turn_id?,
            status,
            started_at,
        })
    }
}

/// Find the latest complete lifecycle record with fixed-size reverse reads.
/// Lines spanning blocks are parsed through a streaming field projection, so
/// large tool output or completion messages do not accumulate in a buffer.
/// Return the last complete-line offset as well, leaving any partial EOF unread.
fn recover_latest_lifecycle(
    file: &mut File,
    len: u64,
) -> io::Result<(Option<RecoveredLifecycle>, u64)> {
    let mut block = vec![0; RECOVERY_BLOCK_BYTES as usize];
    let mut block_end = len;
    let mut line_end = None;
    let mut committed_end = 0;
    while block_end > 0 {
        let block_start = block_end.saturating_sub(RECOVERY_BLOCK_BYTES);
        let bytes = &mut block[..(block_end - block_start) as usize];
        file.seek(SeekFrom::Start(block_start))?;
        file.read_exact(bytes)?;
        for index in (0..bytes.len()).rev().filter(|index| bytes[*index] == b'\n') {
            let next_line_start = block_start + index as u64 + 1;
            if let Some(end) = line_end {
                let event: Option<LifecycleProjection> = if end <= block_end {
                    serde_json::from_slice(&bytes[index + 1..(end - block_start) as usize]).ok()
                } else {
                    file.seek(SeekFrom::Start(next_line_start))?;
                    read_lifecycle_projection((&mut *file).take(end - next_line_start))?
                };
                if let Some(event) = event.and_then(LifecycleProjection::into_lifecycle) {
                    return Ok((Some(event), committed_end));
                }
            } else {
                committed_end = next_line_start;
            }
            line_end = Some(next_line_start - 1);
        }
        block_end = block_start;
    }
    if let Some(end) = line_end {
        file.seek(SeekFrom::Start(0))?;
        let event = read_lifecycle_projection(file.take(end))?;
        return Ok((event.and_then(LifecycleProjection::into_lifecycle), committed_end));
    }
    Ok((None, committed_end))
}

fn read_lifecycle_projection(reader: impl Read) -> io::Result<Option<LifecycleProjection>> {
    match serde_json::from_reader(BufReader::new(reader)) {
        Ok(event) => Ok(Some(event)),
        Err(error) if error.is_io() => Err(io::Error::other(error)),
        Err(_) => Ok(None),
    }
}

/// Re-read the tail of every recently-modified session file and rebuild the
/// active turn status from the latest lifecycle event. This recovers from any
/// event the incremental reader may have skipped (file truncation, partial
/// write, watcher gap) so a Working turn never lingers past its real
/// completion.
fn reconcile_active_turns(runtime: &mut RuntimeState) {
    let now = SystemTime::now();
    let paths: Vec<PathBuf> = runtime.known_files.iter().cloned().collect();
    for path in paths {
        if runtime.ignored_files.contains(&path) || !runtime.file_offsets.contains_key(&path) {
            continue;
        }
        let Ok(metadata) = fs::metadata(&path) else {
            continue;
        };
        let modified = metadata.modified().unwrap_or(UNIX_EPOCH);
        let Ok(age) = now.duration_since(modified) else {
            continue;
        };
        if age > RECENT_FILE_WINDOW {
            continue;
        }
        reconcile_file_tail(runtime, &path);
    }
}

fn reconcile_file_tail(runtime: &mut RuntimeState, path: &Path) {
    let Ok(mut file) = File::open(path) else {
        return;
    };
    let Ok(metadata) = file.metadata() else {
        return;
    };
    let len = metadata.len();
    let start = len.saturating_sub(TAIL_RECONCILE_BYTES);
    if file.seek(SeekFrom::Start(start)).is_err() {
        return;
    }
    let mut reader = BufReader::new(file);
    if start > 0 {
        let mut discard = String::new();
        let _ = reader.read_line(&mut discard);
    }
    // Track the latest lifecycle event per turn seen in the tail.
    let mut latest_by_turn: HashMap<String, (TaskStatus, DateTime<Utc>)> = HashMap::new();
    let mut line = String::new();
    loop {
        line.clear();
        if !matches!(reader.read_line(&mut line), Ok(read) if read > 0)
            || !line.ends_with('\n')
        {
            break;
        }
        if let Some((turn_id, status, ts)) = lifecycle_event(&line) {
            latest_by_turn.insert(turn_id, (status, ts));
        }
    }
    for (turn_id, (status, ts)) in latest_by_turn {
        if let Some(task) = runtime.tasks.get_mut(&turn_id) {
            // Promote Working -> Completed/Error only when the tail proves it.
            if task.status == TaskStatus::Working && status != TaskStatus::Working {
                task.status = status;
                task.finished_at = Some(ts);
                task.duration = (ts - task.started_at).to_std().ok().or(task.duration);
                if task.status != TaskStatus::Working {
                    runtime.active_turn_by_thread.remove(&task.thread_id);
                }
            }
        }
    }
}

fn lifecycle_event(line: &str) -> Option<(String, TaskStatus, DateTime<Utc>)> {
    let Ok(value) = serde_json::from_str::<Value>(line) else {
        return None;
    };
    if value.get("type").and_then(Value::as_str) != Some("event_msg") {
        return None;
    }
    let Some(payload) = value.get("payload") else {
        return None;
    };
    let Some(event_type) = payload.get("type").and_then(Value::as_str) else {
        return None;
    };
    let turn_id = payload.get("turn_id").and_then(Value::as_str)?.to_string();
    let timestamp = parse_timestamp(value.get("timestamp")).unwrap_or_else(Utc::now);
    let status = match event_type {
        "task_started" => TaskStatus::Working,
        "task_complete" | "turn_completed" => TaskStatus::Completed,
        "turn_aborted" | "turn_failed" | "task_failed" => TaskStatus::Error,
        _ => return None,
    };
    Some((turn_id, status, timestamp))
}

fn process_line(
    runtime: &mut RuntimeState,
    path: &Path,
    line: &str,
    live: bool,
    app: Option<&AppHandle>,
) {
    let Ok(value) = serde_json::from_str::<Value>(line) else {
        return;
    };
    if value.get("type").and_then(Value::as_str) != Some("event_msg") {
        return;
    }
    let Some(payload) = value.get("payload") else {
        return;
    };
    let Some(event_type) = payload.get("type").and_then(Value::as_str) else {
        return;
    };
    let timestamp = parse_timestamp(value.get("timestamp")).unwrap_or_else(Utc::now);
    let thread_id = runtime
        .thread_id_by_file
        .get(path)
        .cloned()
        .or_else(|| thread_id_from_path(path))
        .unwrap_or_else(|| "unknown".to_string());

    match event_type {
        "user_message" => {
            let message = payload
                .get("message")
                .and_then(Value::as_str)
                .or_else(|| payload.get("text").and_then(Value::as_str));
            if !runtime.indexed_title_threads.contains(&thread_id)
                && let Some(title) = message.and_then(clean_title)
            {
                runtime
                    .thread_titles
                    .entry(thread_id.clone())
                    .or_insert_with(|| title.clone());
                if let Some(turn_id) = runtime.active_turn_by_thread.get(&thread_id).cloned()
                    && let Some(task) = runtime.tasks.get_mut(&turn_id)
                {
                    task.title = runtime
                        .thread_titles
                        .get(&thread_id)
                        .cloned()
                        .unwrap_or(title);
                }
            }
        }
        "task_started" => {
            let Some(turn_id) = payload.get("turn_id").and_then(Value::as_str) else {
                return;
            };
            let started_at = payload
                .get("started_at")
                .and_then(Value::as_i64)
                .and_then(|seconds| Utc.timestamp_opt(seconds, 0).single())
                .unwrap_or(timestamp);
            start_task(runtime, &thread_id, turn_id, started_at);
        }
        "task_complete" | "turn_completed" => {
            let Some(turn_id) = payload.get("turn_id").and_then(Value::as_str) else {
                return;
            };
            let duration = payload
                .get("duration_ms")
                .and_then(Value::as_u64)
                .map(Duration::from_millis);
            let completed_at = payload
                .get("completed_at")
                .and_then(Value::as_i64)
                .and_then(|seconds| Utc.timestamp_opt(seconds, 0).single())
                .unwrap_or(timestamp);
            let fallback_title = resolve_title(runtime, &thread_id);
            let task = runtime
                .tasks
                .entry(turn_id.to_string())
                .or_insert_with(|| TaskRecord {
                    turn_id: turn_id.to_string(),
                    thread_id: thread_id.clone(),
                    title: fallback_title,
                    status: TaskStatus::Completed,
                    started_at: duration
                        .and_then(|value| chrono::Duration::from_std(value).ok())
                        .map(|value| completed_at - value)
                        .unwrap_or(completed_at),
                    finished_at: Some(completed_at),
                    duration,
                });
            task.status = TaskStatus::Completed;
            task.finished_at = Some(completed_at);
            task.duration = duration.or_else(|| (completed_at - task.started_at).to_std().ok());
            runtime.active_turn_by_thread.remove(&thread_id);

            let notify_duration = task.duration;
            let notify_title = task.title.clone();
            if should_notify_completion(runtime, turn_id, live, notify_duration)
                && let Some(app) = app
            {
                notify_completion(app, &notify_title, notify_duration);
            }
        }
        "turn_aborted" | "turn_failed" | "task_failed" => {
            let Some(turn_id) = payload.get("turn_id").and_then(Value::as_str) else {
                return;
            };
            if let Some(task) = runtime.tasks.get_mut(turn_id) {
                task.status = TaskStatus::Error;
                task.finished_at = Some(timestamp);
                task.duration = (timestamp - task.started_at).to_std().ok();
                let task_thread_id = task.thread_id.clone();
                runtime.active_turn_by_thread.remove(&task_thread_id);
            } else {
                runtime.tasks.insert(
                    turn_id.to_string(),
                    TaskRecord {
                        turn_id: turn_id.to_string(),
                        thread_id: thread_id.clone(),
                        title: resolve_title(runtime, &thread_id),
                        status: TaskStatus::Error,
                        started_at: timestamp,
                        finished_at: Some(timestamp),
                        duration: Some(Duration::ZERO),
                    },
                );
            }
        }
        _ => {}
    }
}

fn start_task(
    runtime: &mut RuntimeState,
    thread_id: &str,
    turn_id: &str,
    started_at: DateTime<Utc>,
) {
    let title = resolve_title(runtime, thread_id);
    // A new start supersedes the previously active turn in this conversation.
    if let Some(previous) = runtime.active_turn_by_thread.get(thread_id).cloned()
        && let Some(task) = runtime.tasks.get_mut(&previous)
        && task.status == TaskStatus::Working
    {
        task.status = TaskStatus::Completed;
        task.finished_at = Some(started_at);
        task.duration = (started_at - task.started_at).to_std().ok();
    }
    runtime
        .active_turn_by_thread
        .insert(thread_id.to_string(), turn_id.to_string());
    runtime.tasks.insert(
        turn_id.to_string(),
        TaskRecord {
            turn_id: turn_id.to_string(),
            thread_id: thread_id.to_string(),
            title,
            status: TaskStatus::Working,
            started_at,
            finished_at: None,
            duration: None,
        },
    );
}

fn resolve_title(runtime: &RuntimeState, thread_id: &str) -> String {
    runtime
        .thread_titles
        .get(thread_id)
        .cloned()
        .unwrap_or_else(|| short_thread_id(thread_id))
}

fn short_thread_id(thread_id: &str) -> String {
    if thread_id.len() >= 8 {
        thread_id.chars().take(8).collect()
    } else {
        thread_id.to_string()
    }
}

fn notify_completion(app: &AppHandle, title: &str, duration: Option<Duration>) {
    let repository = app
        .state::<Mutex<AppState>>()
        .lock()
        .ok()
        .and_then(|state| {
            state
                .account_service
                .as_ref()
                .map(|service| service.repositories().settings.clone())
        });
    let Some(repository) = repository else {
        return;
    };
    let controller = app.state::<Mutex<
        crate::notification_controller::NotificationController<
            crate::notification_controller::WindowsToastSink,
        >,
    >>();
    if let Ok(mut controller) = controller.lock()
        && let Err(error) =
            controller.send_task_completion(&repository, title, duration.unwrap_or(Duration::ZERO))
    {
        tracing::warn!(error = %error, "Codex Desktop completion notification failed");
    }
}

fn should_notify_completion(
    runtime: &mut RuntimeState,
    turn_id: &str,
    live: bool,
    duration: Option<Duration>,
) -> bool {
    live && duration.is_some_and(|value| value >= COMPLETION_SOUND_MINIMUM)
        && runtime.notified_turns.insert(turn_id.to_string())
}

#[derive(Debug, PartialEq, Eq)]
enum SessionMetadata {
    Ready(String),
    Pending,
    Ignored,
}

#[derive(Deserialize)]
struct SessionMetadataProjection {
    #[serde(rename = "type")]
    kind: Option<String>,
    payload: Option<SessionMetadataPayload>,
}

#[derive(Deserialize)]
struct SessionMetadataPayload {
    id: Option<Value>,
    session_id: Option<Value>,
    thread_source: Option<Value>,
    parent_thread_id: Option<Value>,
    agent_nickname: Option<Value>,
}

fn read_session_metadata(path: &Path) -> SessionMetadata {
    let Ok(file) = File::open(path) else {
        return SessionMetadata::Pending;
    };
    // Deserialize only the first object and skip its chat/instruction fields.
    // An incomplete write or temporary I/O failure is retryable; only a
    // complete, definitively unrelated record is permanently ignored.
    let Some(Ok(value)) = serde_json::Deserializer::from_reader(BufReader::new(file))
        .into_iter::<SessionMetadataProjection>()
        .next()
    else {
        return SessionMetadata::Pending;
    };
    if value.kind.as_deref() != Some("session_meta") {
        return SessionMetadata::Ignored;
    }
    let Some(payload) = value.payload else {
        return SessionMetadata::Ignored;
    };
    if payload.thread_source.as_ref().and_then(Value::as_str) == Some("subagent")
        || payload.parent_thread_id.as_ref().and_then(Value::as_str).is_some()
        || payload.agent_nickname.as_ref().and_then(Value::as_str).is_some()
    {
        return SessionMetadata::Ignored;
    }
    let Some(thread_id) = payload.id.as_ref().and_then(Value::as_str)
        .or_else(|| payload.session_id.as_ref().and_then(Value::as_str)) else {
        return SessionMetadata::Ignored;
    };
    if Uuid::parse_str(&thread_id).is_err() {
        return SessionMetadata::Ignored;
    }
    SessionMetadata::Ready(thread_id.to_string())
}

fn prune_tasks(runtime: &mut RuntimeState) {
    // Codex's persisted unread set is not a reliable acknowledgement signal;
    // old terminal turns can linger indefinitely. Keep live turns plus only
    // recently-finished terminal turns so the UI can show "ready/error"
    // transitions without reviving stale history.
    let now = Utc::now();
    runtime.tasks.retain(|turn_id, task| match task.status {
        TaskStatus::Working => runtime.active_turn_by_thread.get(&task.thread_id) == Some(turn_id),
        TaskStatus::Completed | TaskStatus::Error => task.finished_at.is_some_and(|finished| {
            (now - finished)
                .to_std()
                .is_ok_and(|age| age <= RECENT_TERMINAL_TASK_WINDOW)
        }),
    });
}

fn publish_snapshot(app: &AppHandle, runtime: &RuntimeState) {
    let mut latest_by_thread: HashMap<&str, &TaskRecord> = HashMap::new();
    for task in runtime.tasks.values() {
        latest_by_thread
            .entry(&task.thread_id)
            .and_modify(|current| {
                if task_activity_at(task) > task_activity_at(current) {
                    *current = task;
                }
            })
            .or_insert(task);
    }
    let mut tasks: Vec<&TaskRecord> = latest_by_thread.into_values().collect();
    tasks.sort_by(|left, right| {
        status_rank(left.status)
            .cmp(&status_rank(right.status))
            .then_with(|| task_activity_at(right).cmp(&task_activity_at(left)))
    });
    let tasks = tasks
        .into_iter()
        .take(MAX_VISIBLE_TASKS)
        .map(to_dto)
        .collect::<Vec<_>>();

    let store = app.state::<DesktopTaskStore>();
    let Ok(mut current) = store.snapshot.lock() else {
        return;
    };
    if current.tasks == tasks {
        return;
    }
    let snapshot = DesktopTaskSnapshotDto {
        tasks,
        updated_at: Some(Utc::now().to_rfc3339()),
    };
    *current = snapshot.clone();
    drop(current);
    let _ = app.emit(EVENT_NAME, snapshot);
}

fn status_rank(status: TaskStatus) -> u8 {
    match status {
        TaskStatus::Working => 0,
        TaskStatus::Error => 1,
        TaskStatus::Completed => 2,
    }
}

fn task_activity_at(task: &TaskRecord) -> DateTime<Utc> {
    task.finished_at.unwrap_or(task.started_at)
}

fn to_dto(task: &TaskRecord) -> DesktopTaskDto {
    DesktopTaskDto {
        id: task.turn_id.clone(),
        thread_id: task.thread_id.clone(),
        title: task.title.clone(),
        status: match task.status {
            TaskStatus::Working => "working",
            TaskStatus::Completed => "completed",
            TaskStatus::Error => "error",
        }
        .to_string(),
        started_at: task.started_at.to_rfc3339(),
        finished_at: task.finished_at.map(|value| value.to_rfc3339()),
        duration_seconds: task.duration.map(|value| value.as_secs()),
    }
}

fn parse_timestamp(value: Option<&Value>) -> Option<DateTime<Utc>> {
    DateTime::parse_from_rfc3339(value?.as_str()?)
        .ok()
        .map(|value| value.with_timezone(&Utc))
}

fn thread_id_from_path(path: &Path) -> Option<String> {
    let stem = path.file_stem()?.to_str()?;
    if stem.len() < 36 {
        return None;
    }
    let candidate = &stem[stem.len() - 36..];
    Uuid::parse_str(candidate)
        .ok()
        .map(|value| value.to_string())
}

fn clean_title(value: &str) -> Option<String> {
    let collapsed = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.is_empty() {
        return None;
    }
    Some(collapsed.chars().take(72).collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn temp_file(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("codexbar-{name}-{}.jsonl", Uuid::new_v4()))
    }

    fn write_file(path: &Path, text: &str) {
        let mut file = File::create(path).unwrap();
        file.write_all(text.as_bytes()).unwrap();
    }

    fn append_file(path: &Path, text: &str) {
        fs::OpenOptions::new()
            .append(true)
            .open(path)
            .unwrap()
            .write_all(text.as_bytes())
            .unwrap();
    }

    fn session_header(id: &str) -> String {
        format!("{{\"type\":\"session_meta\",\"payload\":{{\"id\":\"{id}\"}}}}\n")
    }

    fn task_event(event_type: &str, turn_id: &str) -> String {
        format!(
            "{{\"type\":\"event_msg\",\"timestamp\":\"2026-09-12T01:00:00Z\",\"payload\":{{\"type\":\"{event_type}\",\"turn_id\":\"{turn_id}\",\"started_at\":1700000000}}}}\n"
        )
    }

    fn output_line(bytes: usize) -> String {
        let prefix = "{\"type\":\"response_item\",\"payload\":{\"output\":\"";
        let suffix = "\"}}\n";
        format!("{prefix}{}{suffix}", "x".repeat(bytes - prefix.len() - suffix.len()))
    }

    #[test]
    fn session_index_accepts_current_id_field_and_skips_bad_lines() {
        let path = temp_file("session-index");
        write_file(
            &path,
            "{not-json}\n{\"id\":\"thread-a\",\"thread_name\":\"Official title\"}\n",
        );
        assert_eq!(
            read_session_index_titles(&path)
                .get("thread-a")
                .map(String::as_str),
            Some("Official title")
        );
        let _ = fs::remove_file(path);
    }

    #[test]
    fn session_metadata_filters_subagents_without_reading_chat_content() {
        let path = temp_file("session-meta");
        let id = Uuid::new_v4();
        write_file(
            &path,
            &format!(
                "{{\"type\":\"session_meta\",\"payload\":{{\"id\":\"{id}\",\"thread_source\":\"subagent\"}}}}\n"
            ),
        );
        assert_eq!(read_session_metadata(&path), SessionMetadata::Ignored);
        write_file(&path, "{\"type\":\"session_meta\",\"payload\":{}}\n");
        assert_eq!(read_session_metadata(&path), SessionMetadata::Ignored);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn bootstrap_recovers_long_running_start_across_reverse_block_boundary() {
        let path = temp_file("long-bootstrap");
        let thread_id = Uuid::new_v4().to_string();
        let event = task_event("task_started", "long-turn");
        // The start's midpoint lands on a reverse-read block boundary, and
        // one large tool response hides it beyond the entire bootstrap tail.
        let output_bytes = RECOVERY_BLOCK_BYTES as usize * 14 - event.len().div_ceil(2);
        write_file(
            &path,
            &format!("{}{}{}", session_header(&thread_id), event, output_line(output_bytes)),
        );
        let mut runtime = RuntimeState::default();
        bootstrap_file(&mut runtime, &path);
        let task = runtime.tasks.get("long-turn").unwrap();
        assert_eq!(task.thread_id, thread_id);
        assert_eq!(task.status, TaskStatus::Working);
        assert_eq!(task.started_at.timestamp(), 1700000000);
        let offset = fs::metadata(&path).unwrap().len();
        assert_eq!(runtime.file_offsets.get(&path), Some(&offset));

        // Unchanged-file polls consume no history and cannot resurrect a
        // record that was already removed from the in-memory snapshot.
        runtime.tasks.clear();
        runtime.active_turn_by_thread.clear();
        process_file_updates(&mut runtime, &path, None);
        assert!(runtime.tasks.is_empty());
        assert_eq!(runtime.file_offsets.get(&path), Some(&offset));
        let _ = fs::remove_file(path);
    }

    #[test]
    fn bootstrap_does_not_resurrect_a_terminal_turn_hidden_before_long_output() {
        for terminal in ["task_complete", "turn_completed", "turn_aborted", "turn_failed", "task_failed"] {
            let path = temp_file("terminal-bootstrap");
            write_file(
                &path,
                &format!(
                    "{}{}{}{}",
                    session_header(&Uuid::new_v4().to_string()),
                    task_event("task_started", "finished-turn"),
                    task_event(terminal, "finished-turn"),
                    output_line(MAX_BOOTSTRAP_BYTES as usize + 256),
                ),
            );
            let mut runtime = RuntimeState::default();
            bootstrap_file(&mut runtime, &path);
            assert!(runtime.tasks.is_empty(), "restored a turn after {terminal}");
            assert!(runtime.active_turn_by_thread.is_empty());
            let _ = fs::remove_file(path);
        }
    }

    #[test]
    fn bootstrap_streams_oversized_completion_without_restoring_its_start() {
        let path = temp_file("large-completion");
        let completion = serde_json::json!({
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "finished-turn",
                "last_agent_message": "x".repeat(MAX_BOOTSTRAP_BYTES as usize + 256),
            },
        });
        write_file(
            &path,
            &format!(
                "{}{}{completion}\n",
                session_header(&Uuid::new_v4().to_string()),
                task_event("task_started", "finished-turn"),
            ),
        );
        let mut runtime = RuntimeState::default();
        bootstrap_file(&mut runtime, &path);
        assert!(runtime.tasks.is_empty());
        assert_eq!(runtime.file_offsets[&path], fs::metadata(&path).unwrap().len());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn new_session_retries_empty_and_half_written_metadata() {
        let path = temp_file("late-metadata");
        let thread_id = Uuid::new_v4().to_string();
        let header = session_header(&thread_id);
        let mut runtime = RuntimeState::default();
        write_file(&path, "");
        bootstrap_file(&mut runtime, &path);
        assert!(!runtime.ignored_files.contains(&path));
        assert!(!runtime.file_offsets.contains_key(&path));
        write_file(&path, &header[..header.len() / 2]);
        process_file_updates(&mut runtime, &path, None);
        assert!(!runtime.ignored_files.contains(&path));
        assert!(runtime.tasks.is_empty());
        append_file(
            &path,
            &format!("{}{}", &header[header.len() / 2..], task_event("task_started", "late-turn")),
        );
        process_file_updates(&mut runtime, &path, None);
        assert_eq!(runtime.tasks["late-turn"].thread_id, thread_id);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn new_session_retries_an_initial_open_failure() {
        let path = temp_file("temporarily-unavailable");
        let mut runtime = RuntimeState::default();
        bootstrap_file(&mut runtime, &path);
        assert!(!runtime.ignored_files.contains(&path));
        write_file(
            &path,
            &format!(
                "{}{}",
                session_header(&Uuid::new_v4().to_string()),
                task_event("task_started", "available-turn"),
            ),
        );
        process_file_updates(&mut runtime, &path, None);
        assert!(runtime.tasks.contains_key("available-turn"));
        let _ = fs::remove_file(path);
    }

    #[test]
    fn confirmed_subagents_and_unrelated_files_are_not_retried() {
        for header in [
            format!("{{\"type\":\"session_meta\",\"payload\":{{\"id\":\"{}\",\"thread_source\":\"subagent\"}}}}\n", Uuid::new_v4()),
            "{\"type\":\"unrelated\",\"payload\":{}}\n".to_string(),
        ] {
            let path = temp_file("ignored-session");
            write_file(&path, &header);
            let mut runtime = RuntimeState::default();
            bootstrap_file(&mut runtime, &path);
            assert!(runtime.ignored_files.contains(&path));
            write_file(
                &path,
                &format!("{}{}", session_header(&Uuid::new_v4().to_string()), task_event("task_started", "ignored-turn")),
            );
            process_file_updates(&mut runtime, &path, None);
            assert!(runtime.tasks.is_empty());
            assert!(!runtime.file_offsets.contains_key(&path));
            let _ = fs::remove_file(path);
        }
    }

    #[test]
    fn bootstrap_and_incremental_reads_keep_unfinished_event_offsets() {
        let path = temp_file("partial-event");
        let header = session_header(&Uuid::new_v4().to_string());
        let start = task_event("task_started", "partial-turn");
        let split = start.len() / 2;
        write_file(&path, &format!("{header}{}", &start[..split]));
        let mut runtime = RuntimeState::default();
        bootstrap_file(&mut runtime, &path);
        assert!(runtime.tasks.is_empty());
        assert_eq!(runtime.file_offsets[&path], header.len() as u64);
        process_file_updates(&mut runtime, &path, None);
        assert_eq!(runtime.file_offsets[&path], header.len() as u64);
        append_file(&path, &start[split..]);
        process_file_updates(&mut runtime, &path, None);
        assert_eq!(runtime.tasks["partial-turn"].status, TaskStatus::Working);

        let completion = task_event("task_complete", "partial-turn");
        let committed = runtime.file_offsets[&path];
        append_file(&path, completion.trim_end());
        process_file_updates(&mut runtime, &path, None);
        reconcile_file_tail(&mut runtime, &path);
        assert_eq!(runtime.file_offsets[&path], committed);
        assert_eq!(runtime.tasks["partial-turn"].status, TaskStatus::Working);
        append_file(&path, "\n");
        process_file_updates(&mut runtime, &path, None);
        assert_eq!(runtime.tasks["partial-turn"].status, TaskStatus::Completed);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn latest_completion_in_bootstrap_tail_wins_over_older_start() {
        let path = temp_file("tail-completion");
        write_file(
            &path,
            &format!(
                "{}{}{}{}{}",
                session_header(&Uuid::new_v4().to_string()),
                task_event("task_started", "old-turn"),
                output_line(MAX_BOOTSTRAP_BYTES as usize + 256),
                task_event("task_started", "new-turn"),
                task_event("task_complete", "new-turn"),
            ),
        );
        let mut runtime = RuntimeState::default();
        bootstrap_file(&mut runtime, &path);
        assert!(runtime.tasks.is_empty());
        assert!(runtime.active_turn_by_thread.is_empty());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn pruning_keeps_a_proven_long_running_turn_without_a_time_limit() {
        let thread_id = Uuid::new_v4().to_string();
        let turn_id = "turn-long".to_string();
        let mut runtime = RuntimeState::default();
        runtime
            .active_turn_by_thread
            .insert(thread_id.clone(), turn_id.clone());
        runtime.tasks.insert(
            turn_id.clone(),
            TaskRecord {
                turn_id,
                thread_id,
                title: "Long task".to_string(),
                status: TaskStatus::Working,
                started_at: Utc::now() - chrono::Duration::hours(8),
                finished_at: None,
                duration: None,
            },
        );
        prune_tasks(&mut runtime);
        assert_eq!(runtime.tasks.len(), 1);
    }

    #[test]
    fn pruning_keeps_recent_terminal_turns_for_ready_and_error_ui_states() {
        let now = Utc::now();
        let thread_id = Uuid::new_v4().to_string();
        let mut runtime = RuntimeState::default();
        runtime.tasks.insert(
            "completed".to_string(),
            TaskRecord {
                turn_id: "completed".to_string(),
                thread_id: thread_id.clone(),
                title: "Done".to_string(),
                status: TaskStatus::Completed,
                started_at: now - chrono::Duration::minutes(2),
                finished_at: Some(now - chrono::Duration::minutes(1)),
                duration: Some(Duration::from_secs(60)),
            },
        );
        runtime.tasks.insert(
            "error".to_string(),
            TaskRecord {
                turn_id: "error".to_string(),
                thread_id,
                title: "Failed".to_string(),
                status: TaskStatus::Error,
                started_at: now - chrono::Duration::minutes(3),
                finished_at: Some(now - chrono::Duration::seconds(30)),
                duration: Some(Duration::from_secs(150)),
            },
        );
        prune_tasks(&mut runtime);
        assert!(runtime.tasks.contains_key("completed"));
        assert!(runtime.tasks.contains_key("error"));
    }

    #[test]
    fn pruning_drops_stale_terminal_turns_outside_recent_window() {
        let thread_id = Uuid::new_v4().to_string();
        let mut runtime = RuntimeState::default();
        let stale_finish = Utc::now() - chrono::Duration::minutes(30);
        runtime.tasks.insert(
            "stale".to_string(),
            TaskRecord {
                turn_id: "stale".to_string(),
                thread_id,
                title: "Old done".to_string(),
                status: TaskStatus::Completed,
                started_at: stale_finish - chrono::Duration::minutes(2),
                finished_at: Some(stale_finish),
                duration: Some(Duration::from_secs(120)),
            },
        );
        prune_tasks(&mut runtime);
        assert!(runtime.tasks.is_empty());
    }

    #[test]
    fn pruning_keeps_terminal_turn_exactly_on_recent_window_boundary() {
        let now = Utc::now();
        let thread_id = Uuid::new_v4().to_string();
        let mut runtime = RuntimeState::default();
        let boundary_finish =
            now - chrono::Duration::seconds(RECENT_TERMINAL_TASK_WINDOW.as_secs() as i64);
        runtime.tasks.insert(
            "boundary".to_string(),
            TaskRecord {
                turn_id: "boundary".to_string(),
                thread_id,
                title: "Boundary".to_string(),
                status: TaskStatus::Completed,
                started_at: boundary_finish - chrono::Duration::minutes(1),
                finished_at: Some(boundary_finish),
                duration: Some(Duration::from_secs(60)),
            },
        );
        prune_tasks(&mut runtime);
        assert!(runtime.tasks.contains_key("boundary"));
    }

    #[test]
    fn completion_notification_is_deduplicated_per_turn() {
        let mut runtime = RuntimeState::default();
        let duration = Some(COMPLETION_SOUND_MINIMUM);
        assert!(should_notify_completion(
            &mut runtime,
            "turn-1",
            true,
            duration
        ));
        assert!(!should_notify_completion(
            &mut runtime,
            "turn-1",
            true,
            duration
        ));
        assert!(!should_notify_completion(
            &mut runtime,
            "turn-2",
            false,
            duration
        ));
    }
}
