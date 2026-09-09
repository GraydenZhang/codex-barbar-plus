use std::{
    collections::{HashMap, HashSet},
    fs::{self, File},
    io::{BufRead, BufReader, Seek, SeekFrom},
    path::{Path, PathBuf},
    sync::Mutex,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use chrono::{DateTime, TimeZone, Utc};
use serde::Serialize;
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};
use uuid::Uuid;

use crate::state::AppState;

const EVENT_NAME: &str = "desktop-task-state-changed";
const MAX_VISIBLE_TASKS: usize = 8;
const MAX_BOOTSTRAP_BYTES: u64 = 768 * 1024;
const TAIL_RECONCILE_BYTES: u64 = 160 * 1024;
const DISCOVERY_INTERVAL_TICKS: u64 = 4;
const POLL_INTERVAL: Duration = Duration::from_millis(500);
const COMPLETION_SOUND_MINIMUM: Duration = Duration::from_secs(3 * 60);
const RECENT_FILE_WINDOW: Duration = Duration::from_secs(15);

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
    let Some((thread_id, is_subagent)) = read_session_metadata(path) else {
        runtime.ignored_files.insert(path.to_path_buf());
        return;
    };
    if is_subagent {
        runtime.ignored_files.insert(path.to_path_buf());
        return;
    }
    runtime
        .thread_id_by_file
        .insert(path.to_path_buf(), thread_id);
    let Ok(mut file) = File::open(path) else {
        return;
    };
    let Ok(metadata) = file.metadata() else {
        return;
    };
    let len = metadata.len();
    let start = len.saturating_sub(MAX_BOOTSTRAP_BYTES);
    if start > 0 && file.seek(SeekFrom::Start(start)).is_ok() {
        let mut discard = String::new();
        let mut reader = BufReader::new(file);
        let _ = reader.read_line(&mut discard);
        for line in reader.lines().map_while(Result::ok) {
            process_line(runtime, path, &line, false, None);
        }
    } else {
        let reader = BufReader::new(file);
        for line in reader.lines().map_while(Result::ok) {
            process_line(runtime, path, &line, false, None);
        }
    }
    runtime.file_offsets.insert(path.to_path_buf(), len);
}

fn process_known_files(app: &AppHandle, runtime: &mut RuntimeState) {
    let paths: Vec<PathBuf> = runtime.known_files.iter().cloned().collect();
    for path in paths {
        if runtime.ignored_files.contains(&path) {
            continue;
        }
        let offset = runtime.file_offsets.get(&path).copied().unwrap_or(0);
        let Ok(mut file) = File::open(&path) else {
            continue;
        };
        let Ok(metadata) = file.metadata() else {
            continue;
        };
        let len = metadata.len();
        if len < offset {
            runtime.file_offsets.insert(path.clone(), 0);
        }
        let start = runtime
            .file_offsets
            .get(&path)
            .copied()
            .unwrap_or(0)
            .min(len);
        if file.seek(SeekFrom::Start(start)).is_err() {
            continue;
        }
        let mut reader = BufReader::new(file);
        let mut line = String::new();
        let mut position = start;
        loop {
            line.clear();
            let Ok(read) = reader.read_line(&mut line) else {
                break;
            };
            if read == 0 {
                break;
            }
            position = position.saturating_add(read as u64);
            process_line(runtime, &path, line.trim_end(), true, Some(app));
        }
        runtime.file_offsets.insert(path, position);
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
    for line in reader.lines().map_while(Result::ok) {
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
            let title = resolve_title(runtime, &thread_id);
            // End any previously active turn in this thread so a new
            // task_started does not leave a stale Working record behind.
            if let Some(previous) = runtime.active_turn_by_thread.get(&thread_id).cloned()
                && let Some(task) = runtime.tasks.get_mut(&previous)
            {
                if task.status == TaskStatus::Working {
                    task.status = TaskStatus::Completed;
                    task.finished_at = Some(started_at);
                    task.duration = (started_at - task.started_at).to_std().ok();
                }
            }
            runtime
                .active_turn_by_thread
                .insert(thread_id.clone(), turn_id.to_string());
            runtime.tasks.insert(
                turn_id.to_string(),
                TaskRecord {
                    turn_id: turn_id.to_string(),
                    thread_id,
                    title,
                    status: TaskStatus::Working,
                    started_at,
                    finished_at: None,
                    duration: None,
                },
            );
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

fn read_session_metadata(path: &Path) -> Option<(String, bool)> {
    let file = File::open(path).ok()?;
    let line = BufReader::new(file).lines().next()?.ok()?;
    let value = serde_json::from_str::<Value>(&line).ok()?;
    if value.get("type").and_then(Value::as_str) != Some("session_meta") {
        return None;
    }
    let payload = value.get("payload")?;
    let thread_id = payload
        .get("id")
        .and_then(Value::as_str)
        .or_else(|| payload.get("session_id").and_then(Value::as_str))?;
    Uuid::parse_str(thread_id).ok()?;
    let is_subagent = payload.get("thread_source").and_then(Value::as_str) == Some("subagent")
        || payload
            .get("parent_thread_id")
            .and_then(Value::as_str)
            .is_some()
        || payload
            .get("agent_nickname")
            .and_then(Value::as_str)
            .is_some();
    Some((thread_id.to_string(), is_subagent))
}

fn prune_tasks(runtime: &mut RuntimeState) {
    // Codex's persisted unread set is not a reliable acknowledgement signal;
    // it can retain old completed subagent turns indefinitely. Only expose
    // turns whose latest lifecycle event still proves that they are running.
    runtime.tasks.retain(|turn_id, task| {
        task.status == TaskStatus::Working
            && runtime.active_turn_by_thread.get(&task.thread_id) == Some(turn_id)
    });
}

fn publish_snapshot(app: &AppHandle, runtime: &RuntimeState) {
    let mut latest_by_thread: HashMap<&str, &TaskRecord> = HashMap::new();
    for task in runtime
        .tasks
        .values()
        .filter(|task| task.status == TaskStatus::Working)
    {
        latest_by_thread
            .entry(&task.thread_id)
            .and_modify(|current| {
                if task.started_at > current.started_at {
                    *current = task;
                }
            })
            .or_insert(task);
    }
    let mut tasks: Vec<&TaskRecord> = latest_by_thread.into_values().collect();
    tasks.sort_by(|left, right| {
        status_rank(left.status)
            .cmp(&status_rank(right.status))
            .then_with(|| right.started_at.cmp(&left.started_at))
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
        assert_eq!(read_session_metadata(&path), Some((id.to_string(), true)));
        write_file(&path, "{\"type\":\"session_meta\",\"payload\":{}}\n");
        assert_eq!(read_session_metadata(&path), None);
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
    fn pruning_drops_completed_and_superseded_turns() {
        let thread_id = Uuid::new_v4().to_string();
        let mut runtime = RuntimeState::default();
        runtime
            .active_turn_by_thread
            .insert(thread_id.clone(), "new".to_string());
        for (turn_id, status) in [
            ("old", TaskStatus::Working),
            ("done", TaskStatus::Completed),
        ] {
            runtime.tasks.insert(
                turn_id.to_string(),
                TaskRecord {
                    turn_id: turn_id.to_string(),
                    thread_id: thread_id.clone(),
                    title: "Task".to_string(),
                    status,
                    started_at: Utc::now(),
                    finished_at: None,
                    duration: None,
                },
            );
        }
        prune_tasks(&mut runtime);
        assert!(runtime.tasks.is_empty());
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
