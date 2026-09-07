#!/usr/bin/env python3
"""Apply codex-barbar-plus additions to a clean codex-barbar v1.0.30 checkout.

The script intentionally performs narrow, checked edits. If the upstream baseline
changes, it fails instead of silently rewriting unrelated UI/shell code.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: Path, marker: str, block: str) -> None:
    text = path.read_text(encoding="utf-8-sig")
    if marker in text:
        return
    path.write_text(text.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")


def copy_overrides(overlay: Path, source: Path) -> None:
    root = overlay / "overrides"
    if not root.is_dir():
        raise RuntimeError(f"override directory missing: {root}")
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        relative = item.relative_to(root)
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        print(f"override {relative}")


def patch_tauri_bridge(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/lib/tauri.ts"
    replace_once(
        path,
        '  getCurrentSurfaceState: "get_current_surface_state",\n  quitApp: "quit_app",\n  getFloatBallMotion: "get_float_ball_motion",',
        '  getCurrentSurfaceState: "get_current_surface_state",\n'
        '  getFlyoutPinned: "get_flyout_pinned",\n'
        '  setFlyoutPinned: "set_flyout_pinned",\n'
        '  getDesktopTaskSnapshot: "get_desktop_task_snapshot",\n'
        '  quitApp: "quit_app",\n'
        '  getFloatBallMotion: "get_float_ball_motion",',
        "tauri command names",
    )
    replace_once(
        path,
        'export const getCurrentSurfaceState = () =>\n  invoke<CurrentSurfaceState>(commands.getCurrentSurfaceState);\n\nexport const quitApp = () => invoke<void>(commands.quitApp);',
        'export const getCurrentSurfaceState = () =>\n'
        '  invoke<CurrentSurfaceState>(commands.getCurrentSurfaceState);\n\n'
        'export const getFlyoutPinned = () =>\n'
        '  invoke<boolean>(commands.getFlyoutPinned);\n\n'
        'export const setFlyoutPinned = (pinned: boolean) =>\n'
        '  invoke<boolean>(commands.setFlyoutPinned, { pinned });\n\n'
        'export const getDesktopTaskSnapshot = () =>\n'
        '  invoke<import("../hooks/useDesktopTasks").DesktopTaskSnapshotDto>(\n'
        '    commands.getDesktopTaskSnapshot,\n'
        '  );\n\n'
        'export const quitApp = () => invoke<void>(commands.quitApp);',
        "tauri bridge exports",
    )


def patch_flyout(source: Path) -> None:
    path = source / "apps/desktop-tauri/src-tauri/src/shell/flyout_window.rs"
    replace_once(
        path,
        'static FLYOUT_INTERACTING: AtomicBool = AtomicBool::new(false);',
        'static FLYOUT_INTERACTING: AtomicBool = AtomicBool::new(false);\n'
        'static FLYOUT_PINNED: AtomicBool = AtomicBool::new(false);',
        "flyout pinned state",
    )
    replace_once(
        path,
        'pub fn should_blur_dismiss() -> bool {\n    !FLYOUT_INTERACTING.load(Ordering::SeqCst)\n}',
        'pub fn is_pinned() -> bool {\n'
        '    FLYOUT_PINNED.load(Ordering::SeqCst)\n'
        '}\n\n'
        'pub fn set_pinned(app: &AppHandle, pinned: bool) -> Result<(), String> {\n'
        '    FLYOUT_PINNED.store(pinned, Ordering::SeqCst);\n'
        '    if let Some(window) = app.get_webview_window(FLYOUT_LABEL) {\n'
        '        // The upstream flyout is already always-on-top. Pinning only\n'
        '        // changes blur-dismiss behavior; keep the original z-order.\n'
        '        window.set_always_on_top(true).map_err(|error| error.to_string())?;\n'
        '    }\n'
        '    Ok(())\n'
        '}\n\n'
        'pub fn should_blur_dismiss() -> bool {\n'
        '    !FLYOUT_INTERACTING.load(Ordering::SeqCst)\n'
        '        && !FLYOUT_PINNED.load(Ordering::SeqCst)\n'
        '}',
        "flyout blur dismiss behavior",
    )


def patch_window_commands(source: Path) -> None:
    path = source / "apps/desktop-tauri/src-tauri/src/commands/window.rs"
    replace_once(
        path,
        '#[tauri::command]\npub fn open_tray_panel(app: tauri::AppHandle) -> Result<(), String> {\n    crate::shell::flyout_window::open_or_focus(&app, None)\n}\n',
        '#[tauri::command]\n'
        'pub fn open_tray_panel(app: tauri::AppHandle) -> Result<(), String> {\n'
        '    crate::shell::flyout_window::open_or_focus(&app, None)\n'
        '}\n\n'
        '#[tauri::command]\n'
        'pub fn get_flyout_pinned() -> bool {\n'
        '    crate::shell::flyout_window::is_pinned()\n'
        '}\n\n'
        '#[tauri::command]\n'
        'pub fn set_flyout_pinned(app: tauri::AppHandle, pinned: bool) -> Result<bool, String> {\n'
        '    crate::shell::flyout_window::set_pinned(&app, pinned)?;\n'
        '    Ok(pinned)\n'
        '}\n',
        "flyout pin commands",
    )


def patch_main(source: Path) -> None:
    path = source / "apps/desktop-tauri/src-tauri/src/main.rs"
    replace_once(
        path,
        'mod commands;\nmod events;',
        'mod commands;\nmod desktop_tasks;\nmod events;',
        "desktop task module",
    )
    replace_once(
        path,
        '.manage(Mutex::new(status_surfaces::StatusSurfaceState::default()))\n        .plugin(',
        '.manage(Mutex::new(status_surfaces::StatusSurfaceState::default()))\n'
        '        .manage(desktop_tasks::DesktopTaskStore::default())\n'
        '        .plugin(',
        "desktop task store",
    )
    replace_once(
        path,
        '            commands::set_flyout_interacting,\n            commands::get_current_surface_state,\n            commands::quit_app,',
        '            commands::set_flyout_interacting,\n'
        '            commands::get_current_surface_state,\n'
        '            commands::get_flyout_pinned,\n'
        '            commands::set_flyout_pinned,\n'
        '            desktop_tasks::get_desktop_task_snapshot,\n'
        '            commands::quit_app,',
        "desktop task and pin command registration",
    )
    replace_once(
        path,
        '            auto_refresh::start(app.handle().clone());\n            notification_controller::start_update_check_loop(app.handle().clone());',
        '            auto_refresh::start(app.handle().clone());\n'
        '            desktop_tasks::start(app.handle().clone());\n'
        '            notification_controller::start_update_check_loop(app.handle().clone());',
        "desktop task monitor startup",
    )


def patch_notification_controller(source: Path) -> None:
    path = source / "apps/desktop-tauri/src-tauri/src/notification_controller.rs"
    insert_before = '''    fn dispatch(\n        &mut self,\n        settings: &AppSettings,\n        events: Vec<V1NotificationEvent>,\n    ) -> Result<(), String> {'''
    method = '''    pub fn send_task_completion(\n        &mut self,\n        repository: &SettingsRepository,\n        task_title: &str,\n        duration: Duration,\n    ) -> Result<(), String> {\n        let settings = load_settings(repository)?;\n        // Completion alerts are a Plus convenience, matching Codexstar's\n        // default long-task ding. The existing play-sound preference still\n        // controls whether the Windows toast is audible.\n        let zh = use_chinese(&settings);\n        let minutes = (duration.as_secs() + 59) / 60;\n        let title = if zh {\n            "Codex 任务已完成"\n        } else {\n            "Codex task completed"\n        };\n        let body = if zh {\n            format!("{task_title}（约 {minutes} 分钟）")\n        } else {\n            format!("{task_title} (~{minutes} min)")\n        };\n        self.sink\n            .send(title, &body, settings.notifications.play_sound)\n            .map_err(|error| map_sink_error(error, "NOTIFICATION_TASK_COMPLETION_FAILED"))\n    }\n\n'''
    replace_once(path, insert_before, method + insert_before, "task completion notification")

    weekly_arm = '''        V1NotificationEvent::WeeklyReset => (\n            if zh {\n                "每周额度已重置"\n            } else {\n                "Weekly allowance reset"\n            }\n            .to_string(),'''
    five_then_weekly = '''        V1NotificationEvent::FiveHourReset => (\n            if zh {\n                "5 小时额度已重置"\n            } else {\n                "5-hour allowance reset"\n            }\n            .to_string(),\n            if zh {\n                "5 小时额度已进入新的周期。".to_string()\n            } else {\n                "The 5-hour allowance started a new cycle.".to_string()\n            },\n        ),\n        V1NotificationEvent::WeeklyReset => (\n            if zh {\n                "每周额度已重置"\n            } else {\n                "Weekly allowance reset"\n            }\n            .to_string(),'''
    replace_once(path, weekly_arm, five_then_weekly, "five-hour reset copy")


def patch_notification_tab(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/settings/tabs/NotificationsTab.tsx"
    text = path.read_text(encoding="utf-8-sig")
    # In Plus, quota-cycle reset alerts are a standalone convenience rather
    # than being suppressed by the upstream master switch. Keep this one
    # switch (and its sound control) usable when the master switch is off.
    old = '''        <NotificationSwitch
          label={copy.notifications.weeklyReset}
          checked={notifications.weeklyResetEnabled}
          disabled={!notifications.enabled}
          onChange={(value) => saveBoolean("weeklyResetEnabled", value)}
        />'''
    new = '''        <NotificationSwitch
          label={copy.notifications.weeklyReset}
          checked={notifications.weeklyResetEnabled}
          onChange={(value) => saveBoolean("weeklyResetEnabled", value)}
        />'''
    if text.count(old) != 1:
        raise RuntimeError("notification tab: weekly reset switch baseline changed")
    text = text.replace(old, new, 1)
    old = '''        <NotificationSwitch
          label={copy.notifications.playSound}
          checked={notifications.playSound}
          disabled={!notifications.enabled}
          onChange={(value) => saveBoolean("playSound", value)}
        />'''
    new = '''        <NotificationSwitch
          label={copy.notifications.playSound}
          checked={notifications.playSound}
          onChange={(value) => saveBoolean("playSound", value)}
        />'''
    if text.count(old) != 1:
        raise RuntimeError("notification tab: sound switch baseline changed")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_notification_labels(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/settings/settingsCopy.ts"
    text = path.read_text(encoding="utf-8-sig")
    replacements = {
        'weeklyReset: "Universal weekly allowance resets"':
            'weeklyReset: "5-hour or weekly allowance resets"',
        'weeklyReset: "通用每周额度完成重置"':
            'weeklyReset: "5 小时或每周额度完成重置"',
    }
    for old, new in replacements.items():
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"notification reset label: expected one {old!r}, got {count}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def patch_taskbar_css(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/TaskbarStatus.css"
    # The Plus capsule renders up to six inline segments (avatar, 5H metric,
    # 5H reset clock, divider, weekly metric, weekly reset date). Switch the
    # main button to a column-flow grid so every segment stays on a single
    # row; the hidden measurement window still reports the real width to the
    # Win32 sizing code, which clamps it to the original taskbar bounds.
    replace_once(
        path,
        "  grid-template-columns: max-content max-content minmax(0, auto) max-content;\n",
        "  grid-auto-flow: column;\n"
        "  grid-auto-columns: max-content;\n",
        "taskbar main single-row grid",
    )
    append_once(
        path,
        "/* codex-barbar-plus: taskbar dual-quota single row */",
        r'''/* codex-barbar-plus: taskbar dual-quota single row */
.taskbar-status__main {
  white-space: nowrap;
}

.taskbar-status__divider {
  color: var(--quota-unknown);
  font-weight: 700;
  line-height: 1;
}

.taskbar-status__metric,
.taskbar-status__reset {
  white-space: nowrap;
}''',
    )


def patch_task_css(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/tray/TrayPanel.css"
    append_once(
        path,
        "/* codex-barbar-plus: desktop task status */",
        r'''/* codex-barbar-plus: desktop task status */
.tray-panel--macos .desktop-task-status {
  gap: 8px;
}

.tray-panel--macos .desktop-task-status__list {
  display: grid;
  gap: 7px;
  max-height: 200px;
  overflow-y: auto;
  padding-right: 2px;
}

.tray-panel--macos .desktop-task-status__row {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 7px 9px;
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 9px;
}

.tray-panel--macos .desktop-task-status__dot {
  width: 7px;
  height: 7px;
  background: var(--tray-accent);
  border-radius: 50%;
  box-shadow: 0 0 8px rgba(48, 209, 88, 0.35);
}

.tray-panel--macos .desktop-task-status__row[data-status="completed"] .desktop-task-status__dot {
  background: var(--tray-warning);
  box-shadow: 0 0 8px rgba(255, 214, 10, 0.28);
}

.tray-panel--macos .desktop-task-status__row[data-status="error"] .desktop-task-status__dot {
  background: var(--tray-critical);
  box-shadow: 0 0 8px rgba(255, 69, 58, 0.3);
}

.tray-panel--macos .desktop-task-status__title {
  min-width: 0;
  overflow: hidden;
  color: var(--tray-fg);
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.tray-panel--macos .desktop-task-status__state,
.tray-panel--macos .desktop-task-status__duration {
  color: var(--tray-fg-muted);
  white-space: nowrap;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.tray-panel--macos .desktop-task-status__row[data-status="working"] .desktop-task-status__state {
  color: var(--tray-accent);
}

.tray-panel--macos .desktop-task-status__row[data-status="completed"] .desktop-task-status__state {
  color: var(--tray-warning);
}

.tray-panel--macos .desktop-task-status__row[data-status="error"] .desktop-task-status__state {
  color: #ffb7b9;
}

[data-theme="light"] .tray-panel--macos .desktop-task-status__row {
  background: rgba(20, 29, 45, 0.035);
  border-color: rgba(43, 52, 77, 0.1);
}''',
    )


def patch_version_branding(source: Path, version: str) -> None:
    # Keep the executable/product name unchanged so the original shell, tray,
    # portable layout and existing settings remain compatible. Only set the
    # semantic version used by the build.
    paths = [
        source / "rust/Cargo.toml",
        source / "apps/desktop-tauri/src-tauri/Cargo.toml",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        text = text.replace('version = "1.0.30"', f'version = "{version}"', 1)
        path.write_text(text, encoding="utf-8")

    package = source / "apps/desktop-tauri/package.json"
    text = package.read_text(encoding="utf-8-sig")
    text = text.replace('"version": "1.0.30"', f'"version": "{version}"', 1)
    package.write_text(text, encoding="utf-8")

    tauri = source / "apps/desktop-tauri/src-tauri/tauri.conf.json"
    text = tauri.read_text(encoding="utf-8-sig")
    text = text.replace('"version": "1.0.30"', f'"version": "{version}"', 1)
    tauri.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--version", default="1.0.30-plus.2")
    args = parser.parse_args()

    source = args.source.resolve()
    overlay = args.overlay.resolve()
    if not (source / "apps/desktop-tauri/src-tauri/tauri.conf.json").is_file():
        raise RuntimeError(f"not a codex-barbar checkout: {source}")

    copy_overrides(overlay, source)
    patch_tauri_bridge(source)
    patch_flyout(source)
    patch_window_commands(source)
    patch_main(source)
    patch_notification_controller(source)
    patch_notification_tab(source)
    patch_notification_labels(source)
    patch_taskbar_css(source)
    patch_task_css(source)
    patch_version_branding(source, args.version)
    print(f"codex-barbar-plus overlay applied ({args.version})")


if __name__ == "__main__":
    main()
