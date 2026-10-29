#!/usr/bin/env python3
"""Apply codex-barbar-plus additions to a clean codex-barbar v1.0.30 checkout.

The script intentionally performs narrow, checked edits. If the upstream baseline
changes, it fails instead of silently rewriting unrelated UI/shell code.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from audit_usage import apply as patch_audit_usage
from audit_ui import apply as patch_audit_ui
from audit_settings import apply as patch_audit_settings
from memory_fixes import apply as patch_memory_fixes


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
    test = source / "apps/desktop-tauri/src/types/bridge.test.ts"
    replace_once(
        test,
        '      getCurrentSurfaceState: "get_current_surface_state",\n'
        '      quitApp: "quit_app",',
        '      getCurrentSurfaceState: "get_current_surface_state",\n'
        '      getFlyoutPinned: "get_flyout_pinned",\n'
        '      setFlyoutPinned: "set_flyout_pinned",\n'
        '      getDesktopTaskSnapshot: "get_desktop_task_snapshot",\n'
        '      quitApp: "quit_app",',
        "bridge command contract test",
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
        '        window\n'
        '            .set_always_on_top(true)\n'
        '            .map_err(|error| error.to_string())?;\n'
        '    }\n'
        '    Ok(())\n'
        '}\n\n'
        'pub fn should_blur_dismiss() -> bool {\n'
        '    !FLYOUT_INTERACTING.load(Ordering::SeqCst) && !FLYOUT_PINNED.load(Ordering::SeqCst)\n'
        '}',
        "flyout blur dismiss behavior",
    )
    replace_once(
        path,
        '    crate::shell::dwm::force_dark_caption(&window);\n    let _ = window.set_resizable(false);\n    let _ = window.set_shadow(true);',
        '    crate::shell::dwm::force_dark_caption(&window);\n'
        '    let _ = window.set_resizable(true);\n'
        '    let _ = window.set_shadow(true);',
        "flyout open resizable",
    )
    replace_once(
        path,
        'fn anchored_rect(app: &AppHandle) -> Option<Rect> {\n'
        '    let window = app.get_webview_window(FLYOUT_LABEL)?;\n'
        '    let monitor = current_monitor(&window)?;\n'
        '    let work = usable_work_rect(&monitor);\n'
        '    let logical = stored_logical_size();\n'
        '    let (width, height) = physical_size_for(&monitor, logical);\n'
        '    Some(place_flyout_sized(work, width, height))\n'
        '}',
        'fn anchored_rect(app: &AppHandle) -> Option<Rect> {\n'
        '    let window = app.get_webview_window(FLYOUT_LABEL)?;\n'
        '    let monitor = current_monitor(&window)?;\n'
        '    let work = usable_work_rect(&monitor);\n'
        '    // Preserve a user resize within the session by reusing the current\n'
        '    // outer size; fall back to the default logical size on first open.\n'
        '    let (width, height) = match window.outer_size() {\n'
        '        Ok(size) if size.width > 0 && size.height > 0 => (size.width as i32, size.height as i32),\n'
        '        _ => physical_size_for(&monitor, stored_logical_size()),\n'
        '    };\n'
        '    Some(place_flyout_sized(work, width, height))\n'
        '}',
        "flyout preserve resized size",
    )
    replace_once(
        path,
        'pub fn set_interacting(active: bool) {\n    FLYOUT_INTERACTING.store(active, Ordering::SeqCst);\n}',
        'pub fn set_interacting(active: bool) {\n'
        '    FLYOUT_INTERACTING.store(active, Ordering::SeqCst);\n'
        '}\n\n'
        'fn is_interacting() -> bool {\n'
        '    FLYOUT_INTERACTING.load(Ordering::SeqCst)\n'
        '}',
        "flyout interaction state",
    )
    replace_once(
        path,
        '    if !window.is_visible().unwrap_or(false) || !should_blur_dismiss() {\n        return;\n    }',
        '    if !window.is_visible().unwrap_or(false) || is_interacting() {\n        return;\n    }',
        "flyout correction independent of pin state",
    )
    replace_once(
        path,
        '    let next = clamp_to_monitor(\n        monitor_rect(&monitor),',
        '    let next = clamp_to_monitor(\n        usable_work_rect(&monitor),',
        "flyout correction uses work area",
    )
    replace_once(
        path,
        '        clamp_to_monitor(\n            monitor_rect(&monitor),',
        '        clamp_to_monitor(\n            usable_work_rect(&monitor),',
        "flyout content sizing uses work area",
    )
    replace_once(
        path,
        '            clamp_to_monitor(\n                monitor_rect(monitor),',
        '            clamp_to_monitor(\n                usable_work_rect(monitor),',
        "flyout explicit open uses work area",
    )
    replace_once(
        path,
        'fn monitor_rect(monitor: &tauri::Monitor) -> Rect {\n'
        '    let size = monitor.size();\n'
        '    let pos = monitor.position();\n'
        '    Rect {\n'
        '        x: pos.x,\n'
        '        y: pos.y,\n'
        '        width: size.width.min(i32::MAX as u32) as i32,\n'
        '        height: size.height.min(i32::MAX as u32) as i32,\n'
        '    }\n'
        '}\n',
        '',
        "remove obsolete full-monitor geometry",
    )


def patch_dwm_resize_frame(source: Path) -> None:
    """Keep the native resize frame (WS_THICKFRAME) on the tray flyout so the
    window edge/resize affordances work after enabling resizable."""
    path = source / "apps/desktop-tauri/src-tauri/src/shell/dwm.rs"
    replace_once(
        path,
        'pub fn force_dark_caption(win: &tauri::WebviewWindow) {\n    force_dark_caption_inner(win, false);\n}',
        'pub fn force_dark_caption(win: &tauri::WebviewWindow) {\n'
        '    force_dark_caption_inner(win, true);\n'
        '}',
        "dwm keep resize frame",
    )
    replace_once(
        path,
        'const WM_GETMINMAXINFO: u32 = 0x0024;\n#[cfg(windows)]\nconst WM_ENTERSIZEMOVE: u32 = 0x0231;',
        'const WM_GETMINMAXINFO: u32 = 0x0024;\n'
        '#[cfg(windows)]\n'
        'const WM_SIZING: u32 = 0x0214;\n'
        '#[cfg(windows)]\n'
        'const WM_ENTERSIZEMOVE: u32 = 0x0231;',
        "dwm sizing message",
    )
    replace_once(
        path,
        '        WM_GETMINMAXINFO => {',
        '''        WM_SIZING => {
            // WM_SIZING supplies a physical-pixel proposed rectangle. Clamp
            // only the edge being dragged, so its opposite edge never turns
            // into whole-window movement at a work-area boundary.
            const MONITOR_DEFAULTTONEAREST: u32 = 2;
            unsafe {
                let hmon = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
                if hmon != 0 && lparam != 0 {
                    let mut mi = MonitorInfo {
                        cb_size: std::mem::size_of::<MonitorInfo>() as u32,
                        rc_monitor: WinRect::default(),
                        rc_work: WinRect::default(),
                        dw_flags: 0,
                    };
                    if GetMonitorInfoW(hmon, &mut mi) != 0 {
                        let rect = &mut *(lparam as *mut WinRect);
                        match wparam {
                            1 | 4 | 7 if rect.left < mi.rc_work.left => rect.left = mi.rc_work.left,
                            2 | 5 | 8 if rect.right > mi.rc_work.right => {
                                rect.right = mi.rc_work.right
                            }
                            _ => {}
                        }
                        match wparam {
                            3 | 4 | 5 if rect.top < mi.rc_work.top => rect.top = mi.rc_work.top,
                            6 | 7 | 8 if rect.bottom > mi.rc_work.bottom => {
                                rect.bottom = mi.rc_work.bottom
                            }
                            _ => {}
                        }
                    }
                }
            }
            1
        }
        WM_GETMINMAXINFO => {''',
        "dwm preserve opposite resize edge",
    )


def patch_tauri_window(source: Path) -> None:
    """Make the tray flyout resizable (vertical focus) with sane min size."""
    path = source / "apps/desktop-tauri/src-tauri/tauri.conf.json"
    replace_once(
        path,
        '        "width": 380,\n        "height": 470,\n        "resizable": false,',
        '        "width": 380,\n'
        '        "height": 580,\n'
        '        "resizable": true,\n'
        '        "minWidth": 360,\n'
        '        "minHeight": 480,',
        "tauri window resizable",
    )


def patch_window_default_size(source: Path) -> None:
    """Unify the runtime default flyout size with tauri.conf.json (380x580)."""
    path = source / "apps/desktop-tauri/src-tauri/src/window_positioner.rs"
    replace_once(
        path,
        'pub const FLYOUT_LOGICAL_SIZE: (u32, u32) = (380, 470);',
        'pub const FLYOUT_LOGICAL_SIZE: (u32, u32) = (380, 580);',
        "flyout default logical size 580",
    )


def patch_styles_css(source: Path) -> None:
    """Fix the upstream tray body rule that resets height to auto, which
    defeats the scrollable panel layout. Force viewport-height sizing."""
    path = source / "apps/desktop-tauri/src/styles.css"
    replace_once(
        path,
        'html[data-surface="tray"],\n'
        'html:has(.tray-panel) body {\n'
        '  height: auto;\n'
        '  min-height: 0;\n'
        '}',
        'html[data-surface="tray"],\n'
        'html:has(.tray-panel) body {\n'
        '  height: 100%;\n'
        '  min-height: 0;\n'
        '  overflow: hidden;\n'
        '}',
        "tray body viewport height",
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
    replace_once(
        path,
        '#[tauri::command]\npub fn set_flyout_interacting(active: bool) {\n'
        '    crate::shell::flyout_window::set_interacting(active);\n'
        '}',
        '#[tauri::command]\npub fn set_flyout_interacting(app: tauri::AppHandle, active: bool) {\n'
        '    crate::shell::flyout_window::set_interacting(active);\n'
        '    if !active {\n'
        '        crate::shell::flyout_window::keep_inside_work_area(&app);\n'
        '    }\n'
        '}',
        "flyout correction after title drag",
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
    replace_once(
        path,
        '                shell::dwm::force_dark_caption(&window);\n                let _ = window.set_resizable(false);',
        '                shell::dwm::force_dark_caption(&window);\n'
        '                let _ = window.set_resizable(true);',
        "flyout window resizable",
    )


def patch_notification_controller(source: Path) -> None:
    path = source / "apps/desktop-tauri/src-tauri/src/notification_controller.rs"
    insert_before = '''    fn dispatch(\n        &mut self,\n        settings: &AppSettings,\n        events: Vec<V1NotificationEvent>,\n    ) -> Result<(), String> {'''
    method = '''    pub fn send_task_completion(\n        &mut self,\n        repository: &SettingsRepository,\n        task_title: &str,\n        duration: Duration,\n    ) -> Result<(), String> {\n        let settings = load_settings(repository)?;\n        if !automatic_notifications_enabled(&settings) {\n            return Ok(());\n        }\n        // Sound remains independent from whether the automatic toast is sent.\n        let zh = use_chinese(&settings);\n        let minutes = (duration.as_secs() + 59) / 60;\n        let title = if zh {\n            "Codex 任务已完成"\n        } else {\n            "Codex task completed"\n        };\n        let body = if zh {\n            format!("{task_title}（约 {minutes} 分钟）")\n        } else {\n            format!("{task_title} (~{minutes} min)")\n        };\n        self.sink\n            .send(title, &body, settings.notifications.play_sound)\n            .map_err(|error| map_sink_error(error, "NOTIFICATION_TASK_COMPLETION_FAILED"))\n    }\n\n'''
    replace_once(path, insert_before, method + insert_before, "task completion notification")
    replace_once(
        path,
        '''    ) -> Result<(), String> {
        for event in events {''',
        '''    ) -> Result<(), String> {
        if !automatic_notifications_enabled(settings) {
            return Ok(());
        }
        for event in events {''',
        "automatic notification master guard",
    )
    append_once(
        path,
        "mod plus_master_switch_tests",
        r'''fn automatic_notifications_enabled(settings: &AppSettings) -> bool {
    settings.notifications.enabled
}

#[cfg(test)]
mod plus_master_switch_tests {
    use super::automatic_notifications_enabled;
    use codexbar::storage::AppSettings;

    #[test]
    fn automatic_notifications_follow_master_switch() {
        let mut settings = AppSettings::default();
        assert!(!automatic_notifications_enabled(&settings));
        settings.notifications.enabled = true;
        assert!(automatic_notifications_enabled(&settings));
    }
}''',
    )

    weekly_arm = '''        V1NotificationEvent::WeeklyReset => (\n            if zh {\n                "每周额度已重置"\n            } else {\n                "Weekly allowance reset"\n            }\n            .to_string(),'''
    five_then_weekly = '''        V1NotificationEvent::FiveHourReset => (\n            if zh {\n                "5 小时额度已重置"\n            } else {\n                "5-hour allowance reset"\n            }\n            .to_string(),\n            if zh {\n                "5 小时额度已进入新的周期。".to_string()\n            } else {\n                "The 5-hour allowance started a new cycle.".to_string()\n            },\n        ),\n        V1NotificationEvent::WeeklyReset => (\n            if zh {\n                "每周额度已重置"\n            } else {\n                "Weekly allowance reset"\n            }\n            .to_string(),'''
    replace_once(path, weekly_arm, five_then_weekly, "five-hour reset copy")


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


def patch_reset_notification_sound_storage(source: Path) -> None:
    path = source / "rust/src/storage/settings_repository.rs"
    replace_once(
        path,
        "#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]\n"
        "#[serde(rename_all = \"camelCase\", default)]\n"
        "pub struct NotificationPreferences {\n",
        "#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]\n"
        "#[serde(rename_all = \"camelCase\")]\n"
        "pub enum NotificationSound {\n"
        "    Default,\n"
        "    Im,\n"
        "    Mail,\n"
        "    Reminder,\n"
        "    Sms,\n"
        "}\n\n"
        "impl NotificationSound {\n"
        "    pub fn id(self) -> &'static str {\n"
        "        match self {\n"
        "            Self::Default => \"default\",\n"
        "            Self::Im => \"im\",\n"
        "            Self::Mail => \"mail\",\n"
        "            Self::Reminder => \"reminder\",\n"
        "            Self::Sms => \"sms\",\n"
        "        }\n"
        "    }\n\n"
        "    pub fn from_id(value: &str) -> Result<Self, String> {\n"
        "        match value {\n"
        "            \"default\" => Ok(Self::Default),\n"
        "            \"im\" => Ok(Self::Im),\n"
        "            \"mail\" => Ok(Self::Mail),\n"
        "            \"reminder\" => Ok(Self::Reminder),\n"
        "            \"sms\" => Ok(Self::Sms),\n"
        "            _ => Err(\"unsupported notification sound\".to_string()),\n"
        "        }\n"
        "    }\n\n"
        "    pub fn toast_uri(self) -> &'static str {\n"
        "        match self {\n"
        "            Self::Default => \"ms-winsoundevent:Notification.Default\",\n"
        "            Self::Im => \"ms-winsoundevent:Notification.IM\",\n"
        "            Self::Mail => \"ms-winsoundevent:Notification.Mail\",\n"
        "            Self::Reminder => \"ms-winsoundevent:Notification.Reminder\",\n"
        "            Self::Sms => \"ms-winsoundevent:Notification.SMS\",\n"
        "        }\n"
        "    }\n"
        "}\n\n"
        "impl Default for NotificationSound {\n"
        "    fn default() -> Self {\n"
        "        Self::Default\n"
        "    }\n"
        "}\n\n"
        "#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]\n"
        "#[serde(rename_all = \"camelCase\", default)]\n"
        "pub struct NotificationPreferences {\n",
        "notification sound enum",
    )
    replace_once(
        path,
        "    pub play_sound: bool,\n    pub warning_enabled: bool,",
        "    pub play_sound: bool,\n    pub reset_sound: NotificationSound,\n    pub warning_enabled: bool,",
        "notification reset sound preference",
    )
    replace_once(
        path,
        "            play_sound: true,\n            warning_enabled: true,",
        "            play_sound: true,\n            reset_sound: NotificationSound::Default,\n            warning_enabled: true,",
        "notification reset sound default",
    )
    replace_once(
        path,
        "    pub play_sound: Option<bool>,\n    pub warning_enabled: Option<bool>,",
        "    pub play_sound: Option<bool>,\n    pub reset_sound: Option<NotificationSound>,\n    pub warning_enabled: Option<bool>,",
        "notification reset sound patch field",
    )
    replace_once(
        path,
        "        if let Some(value) = self.play_sound {\n"
        "            preferences.play_sound = value;\n"
        "        }\n"
        "        if let Some(value) = self.warning_enabled {",
        "        if let Some(value) = self.play_sound {\n"
        "            preferences.play_sound = value;\n"
        "        }\n"
        "        if let Some(value) = self.reset_sound {\n"
        "            preferences.reset_sound = value;\n"
        "        }\n"
        "        if let Some(value) = self.warning_enabled {",
        "apply notification reset sound patch",
    )
    replace_once(
        path,
        "        assert!(notifications.play_sound);\n"
        "        assert!(notifications.warning_enabled);",
        "        assert!(notifications.play_sound);\n"
        "        assert_eq!(notifications.reset_sound, NotificationSound::Default);\n"
        "        assert!(notifications.warning_enabled);",
        "notification reset sound compatibility assertion",
    )
    replace_once(
        path,
        "                    enabled: Some(true),\n"
        "                    play_sound: Some(false),\n"
        "                    warning_enabled: Some(false),",
        "                    enabled: Some(true),\n"
        "                    play_sound: Some(false),\n"
        "                    reset_sound: Some(NotificationSound::Mail),\n"
        "                    warning_enabled: Some(false),",
        "notification reset sound repository patch test",
    )
    replace_once(
        path,
        "        assert_eq!(reloaded.notifications.warning_remaining_percent, 70);",
        "        assert_eq!(reloaded.notifications.warning_remaining_percent, 70);\n"
        "        assert_eq!(reloaded.notifications.reset_sound, NotificationSound::Mail);",
        "notification reset sound repository assertion",
    )

    path = source / "rust/src/storage/mod.rs"
    replace_once(
        path,
        "    AppSettings, DisplayMode, LanguagePreference, NotificationPreferences,\n"
        "    NotificationPreferencesPatch, PanelDensity, PanelPreferences, PanelPreferencesPatch,\n"
        "    SettingsPatch, SettingsRepository, SurfaceAppearancePreferences, TaskbarDensity,\n"
        "    TaskbarPresentationPreferences, TaskbarTrayPreferences, TaskbarTrayPreferencesPatch,\n"
        "    ThemePreference, TrayIconMode,",
        "    AppSettings, DisplayMode, LanguagePreference, NotificationPreferences,\n"
        "    NotificationPreferencesPatch, NotificationSound, PanelDensity, PanelPreferences,\n"
        "    PanelPreferencesPatch, SettingsPatch, SettingsRepository, SurfaceAppearancePreferences,\n"
        "    TaskbarDensity, TaskbarPresentationPreferences, TaskbarTrayPreferences,\n"
        "    TaskbarTrayPreferencesPatch, ThemePreference, TrayIconMode,",
        "notification sound public storage export",
    )


def patch_reset_notification_sound_bridge(source: Path) -> None:
    path = source / "apps/desktop-tauri/src-tauri/src/commands/bridge.rs"
    replace_once(
        path,
        "    NotificationPreferences, NotificationPreferencesPatch, PanelDensity, PanelPreferences,\n"
        "    PanelPreferencesPatch, SettingsPatch, TaskbarDensity, TaskbarPresentationPreferences,\n"
        "    TaskbarTrayPreferencesPatch, ThemePreference,",
        "    NotificationPreferences, NotificationPreferencesPatch, NotificationSound, PanelDensity,\n"
        "    PanelPreferences, PanelPreferencesPatch, SettingsPatch, TaskbarDensity,\n"
        "    TaskbarPresentationPreferences, TaskbarTrayPreferencesPatch, ThemePreference,",
        "notification sound bridge import",
    )
    replace_once(
        path,
        "    pub play_sound: bool,\n    pub warning_enabled: bool,",
        "    pub play_sound: bool,\n    pub reset_sound: &'static str,\n    pub warning_enabled: bool,",
        "notification sound dto field",
    )
    replace_once(
        path,
        "            play_sound: preferences.play_sound,\n"
        "            warning_enabled: preferences.warning_enabled,",
        "            play_sound: preferences.play_sound,\n"
        "            reset_sound: preferences.reset_sound.id(),\n"
        "            warning_enabled: preferences.warning_enabled,",
        "notification sound dto mapping",
    )
    replace_once(
        path,
        "    pub play_sound: Option<bool>,\n    pub warning_enabled: Option<bool>,",
        "    pub play_sound: Option<bool>,\n    pub reset_sound: Option<String>,\n    pub warning_enabled: Option<bool>,",
        "notification sound patch dto",
    )
    replace_once(
        path,
        "        Ok(NotificationPreferencesPatch {\n"
        "            enabled: self.enabled,\n"
        "            play_sound: self.play_sound,\n"
        "            warning_enabled: self.warning_enabled,",
        "        let reset_sound = self\n"
        "            .reset_sound\n"
        "            .map(|value| NotificationSound::from_id(&value))\n"
        "            .transpose()?;\n"
        "        Ok(NotificationPreferencesPatch {\n"
        "            enabled: self.enabled,\n"
        "            play_sound: self.play_sound,\n"
        "            reset_sound,\n"
        "            warning_enabled: self.warning_enabled,",
        "notification sound patch mapping",
    )

    path = source / "apps/desktop-tauri/src-tauri/src/commands/settings.rs"
    replace_once(
        path,
        "            notifications: Some(NotificationPreferencesPatchDto {\n"
        "                enabled: Some(true),\n"
        "                play_sound: Some(false),\n"
        "                warning_enabled: Some(false),",
        "            notifications: Some(NotificationPreferencesPatchDto {\n"
        "                enabled: Some(true),\n"
        "                play_sound: Some(false),\n"
        "                reset_sound: Some(\"reminder\".to_string()),\n"
        "                warning_enabled: Some(false),",
        "notification sound settings command input test",
    )
    replace_once(
        path,
        "            Some(NotificationPreferencesPatch {\n"
        "                enabled: Some(true),\n"
        "                play_sound: Some(false),\n"
        "                warning_enabled: Some(false),",
        "            Some(NotificationPreferencesPatch {\n"
        "                enabled: Some(true),\n"
        "                play_sound: Some(false),\n"
        "                reset_sound: Some(NotificationSound::Reminder),\n"
        "                warning_enabled: Some(false),",
        "notification sound settings command expectation",
    )

    path = source / "apps/desktop-tauri/src/types/bridge.ts"
    replace_once(
        path,
        "export interface NotificationPreferencesDto {\n"
        "  enabled: boolean;\n"
        "  playSound: boolean;\n",
        "export type NotificationSound =\n"
        "  | \"default\"\n"
        "  | \"im\"\n"
        "  | \"mail\"\n"
        "  | \"reminder\"\n"
        "  | \"sms\";\n\n"
        "export interface NotificationPreferencesDto {\n"
        "  enabled: boolean;\n"
        "  playSound: boolean;\n"
        "  resetSound: NotificationSound;\n",
        "notification sound TypeScript contract",
    )

    path = source / "apps/desktop-tauri/src/lib/tauri.ts"
    replace_once(
        path,
        '  sendTestNotification: "send_test_notification",\n',
        '  sendTestNotification: "send_test_notification",\n'
        '  previewNotificationSound: "preview_notification_sound",\n',
        "notification sound preview command name",
    )
    replace_once(
        path,
        '  FloatBallMotionDto,\n} from "../types/bridge";',
        '  FloatBallMotionDto,\n  NotificationSound,\n} from "../types/bridge";',
        "notification sound bridge type import",
    )
    replace_once(
        path,
        "export const sendTestNotification = () =>\n"
        "  invoke<void>(commands.sendTestNotification);\n",
        "export const sendTestNotification = () =>\n"
        "  invoke<void>(commands.sendTestNotification);\n\n"
        "export const previewNotificationSound = (sound: NotificationSound) =>\n"
        "  invoke<void>(commands.previewNotificationSound, { sound });\n",
        "notification sound preview bridge export",
    )
    path = source / "apps/desktop-tauri/src/types/bridge.test.ts"
    replace_once(
        path,
        '      sendTestNotification: "send_test_notification",\n',
        '      sendTestNotification: "send_test_notification",\n'
        '      previewNotificationSound: "preview_notification_sound",\n',
        "notification sound preview command contract",
    )


def patch_reset_notification_sound_controller(source: Path) -> None:
    path = source / "apps/desktop-tauri/src-tauri/src/notification_controller.rs"
    replace_once(
        path,
        "    storage::{AppSettings, LanguagePreference, SettingsRepository},",
        "    storage::{AppSettings, LanguagePreference, NotificationSound, SettingsRepository},",
        "notification sound controller import",
    )
    replace_once(
        path,
        "pub trait ToastSink: Send {\n"
        "    fn send(&mut self, title: &str, body: &str, play_sound: bool) -> Result<(), String>;\n"
        "}",
        "pub trait ToastSink: Send {\n"
        "    fn send(&mut self, title: &str, body: &str, play_sound: bool) -> Result<(), String>;\n\n"
        "    fn send_with_sound(\n"
        "        &mut self,\n"
        "        title: &str,\n"
        "        body: &str,\n"
        "        play_sound: bool,\n"
        "        _sound: NotificationSound,\n"
        "    ) -> Result<(), String> {\n"
        "        self.send(title, body, play_sound)\n"
        "    }\n"
        "}",
        "toast sink selected sound support",
    )
    replace_once(
        path,
        "impl ToastSink for WindowsToastSink {\n"
        "    fn send(&mut self, title: &str, body: &str, play_sound: bool) -> Result<(), String> {\n"
        "        send_windows_toast(title, body, play_sound)\n"
        "    }\n"
        "}",
        "impl ToastSink for WindowsToastSink {\n"
        "    fn send(&mut self, title: &str, body: &str, play_sound: bool) -> Result<(), String> {\n"
        "        send_windows_toast(title, body, play_sound, None)\n"
        "    }\n\n"
        "    fn send_with_sound(\n"
        "        &mut self,\n"
        "        title: &str,\n"
        "        body: &str,\n"
        "        play_sound: bool,\n"
        "        sound: NotificationSound,\n"
        "    ) -> Result<(), String> {\n"
        "        send_windows_toast(title, body, play_sound, Some(sound))\n"
        "    }\n"
        "}",
        "Windows toast selected sound support",
    )
    replace_once(
        path,
        "    pub fn send_task_completion(\n",
        "    pub fn preview_sound(\n"
        "        &mut self,\n"
        "        repository: &SettingsRepository,\n"
        "        sound: NotificationSound,\n"
        "    ) -> Result<(), String> {\n"
        "        let settings = load_settings(repository)?;\n"
        "        let (title, body) = sound_preview_copy(&settings);\n"
        "        self.sink\n"
        "            .send_with_sound(title, body, true, sound)\n"
        "            .map_err(|error| map_sink_error(error, \"NOTIFICATION_SOUND_PREVIEW_FAILED\"))\n"
        "    }\n\n"
        "    pub fn send_task_completion(\n",
        "notification sound preview controller",
    )
    replace_once(
        path,
        "        for event in events {\n"
        "            let (title, body) = event_copy(settings, &event);\n"
        "            self.sink\n"
        "                .send(&title, &body, settings.notifications.play_sound)\n"
        "                .map_err(|error| map_sink_error(error, \"NOTIFICATION_DISPATCH_FAILED\"))?;\n"
        "        }",
        "        for event in events {\n"
        "            let (title, body) = event_copy(settings, &event);\n"
        "            let result = if matches!(\n"
        "                event,\n"
        "                V1NotificationEvent::FiveHourReset | V1NotificationEvent::WeeklyReset\n"
        "            ) {\n"
        "                self.sink.send_with_sound(\n"
        "                    &title,\n"
        "                    &body,\n"
        "                    settings.notifications.play_sound,\n"
        "                    settings.notifications.reset_sound,\n"
        "                )\n"
        "            } else {\n"
        "                self.sink\n"
        "                    .send(&title, &body, settings.notifications.play_sound)\n"
        "            };\n"
        "            result.map_err(|error| map_sink_error(error, \"NOTIFICATION_DISPATCH_FAILED\"))?;\n"
        "        }",
        "reset notifications use selected sound",
    )
    replace_once(
        path,
        "fn test_copy(settings: &AppSettings) -> (&'static str, &'static str) {",
        "fn sound_preview_copy(settings: &AppSettings) -> (&'static str, &'static str) {\n"
        "    if use_chinese(settings) {\n"
        "        (\n"
        "            \"重置通知提示音试听\",\n"
        "            \"这是 5 小时或每周额度重置通知的提示音。\",\n"
        "        )\n"
        "    } else {\n"
        "        (\n"
        "            \"Reset notification sound preview\",\n"
        "            \"This is the sound for 5-hour or weekly allowance resets.\",\n"
        "        )\n"
        "    }\n"
        "}\n\n"
        "fn test_copy(settings: &AppSettings) -> (&'static str, &'static str) {",
        "notification sound preview copy",
    )
    replace_once(
        path,
        "fn send_windows_toast(title: &str, body: &str, play_sound: bool) -> Result<(), String> {\n"
        "    send_windows_toast_with(&SystemNotificationSettingProbe, true, || {\n"
        "        run_windows_toast_transport(title, body, play_sound)\n"
        "    })\n"
        "}\n\n"
        "fn windows_toast_script(title: &str, body: &str, play_sound: bool) -> String {\n"
        "    let audio = if play_sound {\n"
        "        \"\"\n"
        "    } else {\n"
        "        r#\"<audio silent=\"true\"/>\"#\n"
        "    };",
        "fn send_windows_toast(\n"
        "    title: &str,\n"
        "    body: &str,\n"
        "    play_sound: bool,\n"
        "    sound: Option<NotificationSound>,\n"
        ") -> Result<(), String> {\n"
        "    send_windows_toast_with(&SystemNotificationSettingProbe, true, || {\n"
        "        run_windows_toast_transport(title, body, play_sound, sound)\n"
        "    })\n"
        "}\n\n"
        "fn windows_toast_script(\n"
        "    title: &str,\n"
        "    body: &str,\n"
        "    play_sound: bool,\n"
        "    sound: Option<NotificationSound>,\n"
        ") -> String {\n"
        "    let audio = if !play_sound {\n"
        "        r#\"<audio silent=\"true\"/>\"#.to_string()\n"
        "    } else if let Some(sound) = sound {\n"
        "        format!(r#\"<audio src=\"{}\"/>\"#, sound.toast_uri())\n"
        "    } else {\n"
        "        String::new()\n"
        "    };",
        "Windows toast audio payload",
    )
    replace_once(
        path,
        "fn run_windows_toast_transport(title: &str, body: &str, play_sound: bool) -> Result<(), String> {",
        "fn run_windows_toast_transport(\n"
        "    title: &str,\n"
        "    body: &str,\n"
        "    play_sound: bool,\n"
        "    sound: Option<NotificationSound>,\n"
        ") -> Result<(), String> {",
        "Windows toast transport sound argument",
    )
    replace_once(
        path,
        "    let script = windows_toast_script(title, body, play_sound);",
        "    let script = windows_toast_script(title, body, play_sound, sound);",
        "Windows toast script sound argument",
    )
    replace_once(
        path,
        "fn send_windows_toast(_title: &str, _body: &str, _play_sound: bool) -> Result<(), String> {",
        "fn send_windows_toast(\n"
        "    _title: &str,\n"
        "    _body: &str,\n"
        "    _play_sound: bool,\n"
        "    _sound: Option<NotificationSound>,\n"
        ") -> Result<(), String> {",
        "non-Windows toast sound argument",
    )
    replace_once(
        path,
        '        let script = windows_toast_script("Title", "Body", false);',
        '        let script = windows_toast_script("Title", "Body", false, None);',
        "silent toast test sound argument",
    )
    append_once(
        path,
        "fn selected_reset_sound_is_written_to_toast_xml()",
        r'''#[cfg(test)]
mod plus_sound_tests {
    use codexbar::storage::NotificationSound;

    use super::windows_toast_script;

    #[test]
    fn selected_reset_sound_is_written_to_toast_xml() {
        let script = windows_toast_script("Title", "Body", true, Some(NotificationSound::Reminder));
        assert!(script.contains(r#"<audio src="ms-winsoundevent:Notification.Reminder"/>"#));
    }

    #[test]
    fn sound_preview_can_force_audio_while_automatic_sound_is_configurable() {
        let audible = windows_toast_script("Title", "Body", true, Some(NotificationSound::Mail));
        let silent = windows_toast_script("Title", "Body", false, Some(NotificationSound::Mail));
        assert!(audible.contains("Notification.Mail"));
        assert!(silent.contains(r#"<audio silent="true"/>"#));
        assert!(!silent.contains("Notification.Mail"));
    }
}''',
    )

    path = source / "apps/desktop-tauri/src-tauri/src/commands/settings.rs"
    replace_once(
        path,
        "use codexbar::storage::SettingsPatch;",
        "use codexbar::storage::{NotificationSound, SettingsPatch};",
        "notification sound settings command import",
    )
    replace_once(
        path,
        "fn send_test_notification_with<F>(\n",
        "#[tauri::command]\n"
        "pub fn preview_notification_sound(\n"
        "    app: tauri::AppHandle,\n"
        "    sound: String,\n"
        "    state: tauri::State<'_, Mutex<AppState>>,\n"
        "    controller: tauri::State<'_, Mutex<NotificationController<WindowsToastSink>>>,\n"
        ") -> Result<(), String> {\n"
        "    let sound = NotificationSound::from_id(&sound)\n"
        "        .map_err(|_| \"NOTIFICATION_SOUND_PREVIEW_FAILED\".to_string())?;\n"
        "    let capability = notification_capability();\n"
        "    let proof_mode = crate::proof_harness::is_proof_mode(&app);\n"
        "    send_test_notification_with(proof_mode, capability, || {\n"
        "        let repository = settings_repository(&state)?;\n"
        "        controller\n"
        "            .lock()\n"
        "            .map_err(|_| \"NOTIFICATION_SOUND_PREVIEW_FAILED\".to_string())?\n"
        "            .preview_sound(&repository, sound)\n"
        "            .map_err(map_notification_sound_preview_error)\n"
        "    })\n"
        "    .map_err(map_notification_sound_preview_error)\n"
        "}\n\n"
        "fn map_notification_sound_preview_error(error: String) -> String {\n"
        "    if error == \"NOTIFICATION_PERMISSION_DISABLED\" {\n"
        "        error\n"
        "    } else {\n"
        "        \"NOTIFICATION_SOUND_PREVIEW_FAILED\".to_string()\n"
        "    }\n"
        "}\n\n"
        "fn send_test_notification_with<F>(\n",
        "notification sound preview command",
    )
    path = source / "apps/desktop-tauri/src-tauri/src/main.rs"
    replace_once(
        path,
        "            commands::send_test_notification,\n",
        "            commands::send_test_notification,\n"
        "            commands::preview_notification_sound,\n",
        "notification sound preview command registration",
    )


def patch_reset_notification_sound_ui(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/settings/tabs/NotificationsTab.tsx"
    replace_once(
        path,
        "  openWindowsNotificationSettings,\n  sendTestNotification,\n",
        "  openWindowsNotificationSettings,\n  previewNotificationSound,\n  sendTestNotification,\n",
        "notification sound preview UI import",
    )
    replace_once(
        path,
        "  NotificationCapabilityDto,\n  SettingsPatchDto,",
        "  NotificationCapabilityDto,\n  NotificationSound,\n  SettingsPatchDto,",
        "notification sound UI type import",
    )
    replace_once(
        path,
        "type NotificationBooleanField =",
        "const RESET_SOUNDS: readonly NotificationSound[] = [\n"
        "  \"default\",\n"
        "  \"im\",\n"
        "  \"mail\",\n"
        "  \"reminder\",\n"
        "  \"sms\",\n"
        "];\n\n"
        "type NotificationBooleanField =",
        "notification sound UI options",
    )
    replace_once(
        path,
        "  sendTest = sendTestNotification,\n  getCapability = getNotificationCapability,",
        "  sendTest = sendTestNotification,\n"
        "  previewSound = previewNotificationSound,\n"
        "  getCapability = getNotificationCapability,",
        "notification sound preview UI dependency",
    )
    replace_once(
        path,
        "  sendTest?: () => Promise<void>;\n  getCapability?: () => Promise<NotificationCapabilityDto>;",
        "  sendTest?: () => Promise<void>;\n"
        "  previewSound?: (sound: NotificationSound) => Promise<void>;\n"
        "  getCapability?: () => Promise<NotificationCapabilityDto>;",
        "notification sound preview UI prop",
    )
    replace_once(
        path,
        "  const [testing, setTesting] = useState(false);\n"
        "  const [openingSettings, setOpeningSettings] = useState(false);",
        "  const [testing, setTesting] = useState(false);\n"
        "  const [previewingSound, setPreviewingSound] = useState(false);\n"
        "  const [openingSettings, setOpeningSettings] = useState(false);",
        "notification sound preview UI state",
    )
    replace_once(
        path,
        "  const openNotificationRecovery = () => {",
        "  const runSoundPreview = (sound: NotificationSound, save: boolean) => {\n"
        "    setError(null);\n"
        "    setTestSent(false);\n"
        "    if (capabilityLoading || capability?.status !== \"available\") {\n"
        "      return;\n"
        "    }\n"
        "    setPreviewingSound(true);\n"
        "    const saveSound = save\n"
        "      ? update({ notifications: { resetSound: sound } })\n"
        "      : Promise.resolve();\n"
        "    void saveSound\n"
        "      .then(() => previewSound(sound))\n"
        "      .catch((reason: unknown) => {\n"
        "        if (reason === \"NOTIFICATION_PERMISSION_DISABLED\") {\n"
        "          refreshCapability();\n"
        "          return;\n"
        "        }\n"
        "        setError(\n"
        "          save ? copy.notifications.saveFailed : copy.notifications.soundPreviewFailed,\n"
        "        );\n"
        "      })\n"
        "      .finally(() => setPreviewingSound(false));\n"
        "  };\n\n"
        "  const openNotificationRecovery = () => {",
        "notification sound preview UI action",
    )
    replace_once(
        path,
        "        <NotificationSwitch\n"
        "          label={copy.notifications.weeklyReset}\n"
        "          checked={notifications.weeklyResetEnabled}\n"
        "          disabled={!notifications.enabled}\n"
        "          onChange={(value) => saveBoolean(\"weeklyResetEnabled\", value)}\n"
        "        />\n"
        "        <div className=\"settings-field\">",
        "        <NotificationSwitch\n"
        "          label={copy.notifications.weeklyReset}\n"
        "          checked={notifications.weeklyResetEnabled}\n"
        "          disabled={!notifications.enabled}\n"
        "          onChange={(value) => saveBoolean(\"weeklyResetEnabled\", value)}\n"
        "        />\n"
        "        <p className=\"settings-field\">\n"
        "          <label htmlFor=\"notification-reset-sound\">\n"
        "            {copy.notifications.resetSound}\n"
        "          </label>\n"
        "          <select\n"
        "            id=\"notification-reset-sound\"\n"
        "            value={notifications.resetSound}\n"
        "            disabled={\n"
        "              capabilityLoading ||\n"
        "              capability?.status !== \"available\" ||\n"
        "              previewingSound\n"
        "            }\n"
        "            onChange={(event) =>\n"
        "              runSoundPreview(event.target.value as NotificationSound, true)\n"
        "            }\n"
        "          >\n"
        "            {RESET_SOUNDS.map((sound) => (\n"
        "              <option key={sound} value={sound}>\n"
        "                {copy.notifications.soundOptions[sound]}\n"
        "              </option>\n"
        "            ))}\n"
        "          </select>\n"
        "          <button\n"
        "            type=\"button\"\n"
        "            disabled={\n"
        "              capabilityLoading ||\n"
        "              capability?.status !== \"available\" ||\n"
        "              previewingSound\n"
        "            }\n"
        "            onClick={() => runSoundPreview(notifications.resetSound, false)}\n"
        "          >\n"
        "            {previewingSound\n"
        "              ? copy.notifications.previewingSound\n"
        "              : copy.notifications.previewSound}\n"
        "          </button>\n"
        "          <small>{copy.notifications.resetSoundDescription}</small>\n"
        "        </p>\n"
        "        <div className=\"settings-field\">",
        "notification sound selector and preview",
    )

    path = source / "apps/desktop-tauri/src/surfaces/settings/settingsCopy.ts"
    replace_once(
        path,
        "    playSound: string;\n    sendTest: string;",
        "    playSound: string;\n"
        "    resetSound: string;\n"
        "    resetSoundDescription: string;\n"
        "    soundOptions: Record<\"default\" | \"im\" | \"mail\" | \"reminder\" | \"sms\", string>;\n"
        "    previewSound: string;\n"
        "    previewingSound: string;\n"
        "    soundPreviewFailed: string;\n"
        "    sendTest: string;",
        "notification sound copy contract",
    )
    replace_once(
        path,
        '    playSound: "Play a sound with notifications",\n'
        '    sendTest: "Send test notification",',
        '    playSound: "Play a sound with notifications",\n'
        '    resetSound: "Reset notification sound",\n'
        '    resetSoundDescription: "Selecting a sound previews it immediately. Previewing sends one local Windows notification.",\n'
        '    soundOptions: { default: "Default", im: "Instant message", mail: "Mail", reminder: "Reminder", sms: "SMS" },\n'
        '    previewSound: "Preview sound",\n'
        '    previewingSound: "Previewing…",\n'
        '    soundPreviewFailed: "Windows could not preview this sound. Check notification settings and try again.",\n'
        '    sendTest: "Send test notification",',
        "English notification sound copy",
    )
    replace_once(
        path,
        '    playSound: "通知时播放声音",\n'
        '    sendTest: "发送测试通知",',
        '    playSound: "通知时播放声音",\n'
        '    resetSound: "重置通知提示音",\n'
        '    resetSoundDescription: "选择后会立即试听；试听会发送一条本地 Windows 预览通知。",\n'
        '    soundOptions: { default: "默认", im: "即时消息", mail: "邮件", reminder: "提醒", sms: "短信" },\n'
        '    previewSound: "试听",\n'
        '    previewingSound: "正在试听…",\n'
        '    soundPreviewFailed: "Windows 无法试听该提示音，请检查通知设置后重试。",\n'
        '    sendTest: "发送测试通知",',
        "Chinese notification sound copy",
    )

    path = source / "apps/desktop-tauri/src/surfaces/settings/tabs/NotificationsTab.test.tsx"
    replace_once(
        path,
        "    playSound: true,\n    warningEnabled: true,",
        "    playSound: true,\n    resetSound: \"default\",\n    warningEnabled: true,",
        "notification sound UI test fixture",
    )
    append_once(
        path,
        'it("saves and previews the selected reset notification sound")',
        r'''describe("Plus reset notification sounds", () => {
  it("saves and previews the selected reset notification sound", async () => {
    const update = vi.fn().mockResolvedValue(settings);
    const previewSound = vi.fn().mockResolvedValue(undefined);
    render(
      <NotificationsTab
        settings={{
          ...settings,
          notifications: { ...settings.notifications, enabled: true },
        }}
        update={update}
        copy={settingsCopy("en-US")}
        previewSound={previewSound}
        getCapability={vi.fn().mockResolvedValue({
          status: "available",
          canOpenSettings: true,
        })}
      />,
    );

    const sound = await screen.findByRole("combobox", {
      name: "Reset notification sound",
    });
    await waitFor(() => expect(sound).toBeEnabled());
    fireEvent.change(sound, { target: { value: "reminder" } });

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith({
        notifications: { resetSound: "reminder" },
      });
      expect(previewSound).toHaveBeenCalledWith("reminder");
    });
  });

  it("previews the saved reset sound again without rewriting settings", async () => {
    const update = vi.fn().mockResolvedValue(settings);
    const previewSound = vi.fn().mockResolvedValue(undefined);
    render(
      <NotificationsTab
        settings={{
          ...settings,
          notifications: {
            ...settings.notifications,
            enabled: true,
            resetSound: "mail",
          },
        }}
        update={update}
        copy={settingsCopy("en-US")}
        previewSound={previewSound}
        getCapability={vi.fn().mockResolvedValue({
          status: "available",
          canOpenSettings: true,
        })}
      />,
    );

    const preview = await screen.findByRole("button", { name: "Preview sound" });
    await waitFor(() => expect(preview).toBeEnabled());
    fireEvent.click(preview);

    await waitFor(() => expect(previewSound).toHaveBeenCalledWith("mail"));
    expect(update).not.toHaveBeenCalled();
  });

  it("allows an explicit preview while automatic notifications are off", async () => {
    const previewSound = vi.fn().mockResolvedValue(undefined);
    render(
      <NotificationsTab
        settings={{
          ...settings,
          notifications: {
            ...settings.notifications,
            enabled: false,
            weeklyResetEnabled: false,
            resetSound: "sms",
          },
        }}
        update={vi.fn().mockResolvedValue(settings)}
        copy={settingsCopy("en-US")}
        previewSound={previewSound}
        getCapability={vi.fn().mockResolvedValue({
          status: "available",
          canOpenSettings: true,
        })}
      />,
    );

    const preview = await screen.findByRole("button", { name: "Preview sound" });
    await waitFor(() => expect(preview).toBeEnabled());
    fireEvent.click(preview);

    await waitFor(() => expect(previewSound).toHaveBeenCalledWith("sms"));
  });
});''',
    )

    fixture_replacements = [
        (
            "apps/desktop-tauri/src/hooks/useSettings.ts",
            "    playSound: true,\n    warningEnabled: true,",
            "    playSound: true,\n    resetSound: \"default\",\n    warningEnabled: true,",
        ),
        (
            "apps/desktop-tauri/src/hooks/useStatusSurface.ts",
            "      playSound: true,\n      warningEnabled: true,",
            "      playSound: true,\n      resetSound: \"default\",\n      warningEnabled: true,",
        ),
        (
            "apps/desktop-tauri/src/test/profileUsageFixtures.ts",
            "    playSound: true,\n    warningEnabled: true,",
            "    playSound: true,\n    resetSound: \"default\",\n    warningEnabled: true,",
        ),
        (
            "apps/desktop-tauri/src/hooks/useSettings.test.tsx",
            "      playSound: true,\n      warningEnabled: true,",
            "      playSound: true,\n      resetSound: \"default\",\n      warningEnabled: true,",
        ),
    ]
    for relative, old, new in fixture_replacements:
        replace_once(
            source / relative,
            old,
            new,
            f"notification sound default fixture ({relative})",
        )

    path = source / "apps/desktop-tauri/src/types/bridge.test.ts"
    replace_once(
        path,
        "        enabled: false,\n"
        "        playSound: true,\n"
        "        warningEnabled: true,",
        "        enabled: false,\n"
        "        playSound: true,\n"
        "        resetSound: \"default\",\n"
        "        warningEnabled: true,",
        "notification sound bridge input fixture",
    )
    replace_once(
        path,
        "      enabled: false,\n"
        "      playSound: true,\n"
        "      warningEnabled: true,",
        "      enabled: false,\n"
        "      playSound: true,\n"
        "      resetSound: \"default\",\n"
        "      warningEnabled: true,",
        "notification sound bridge expectation",
    )


def patch_freshness_setting(source: Path) -> None:
    """The timestamp now has one fixed meaning and location in the header.
    Keep the persisted legacy field readable, but remove its obsolete toggle."""
    path = source / "apps/desktop-tauri/src/surfaces/settings/tabs/MenuTab.tsx"
    replace_once(
        path,
        '''            <PanelToggle
              label={panelCopy.showFreshness}
              checked={panel.showFreshness}
              disabled={saving}
              onChange={(value) => void commit({ showFreshness: value })}
            />
''',
        '',
        "remove obsolete freshness toggle",
    )
    test_path = source / "apps/desktop-tauri/src/surfaces/settings/tabs/MenuTab.test.tsx"
    replace_once(
        test_path,
        '''    fireEvent.click(screen.getByRole("checkbox", { name: "Show data freshness" }));
    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith("update_settings", {
        patch: { panel: { showFreshness: false } },
      }),
    );
''',
        '''    expect(
      screen.queryByRole("checkbox", { name: "Show data freshness" }),
    ).not.toBeInTheDocument();
''',
        "freshness toggle test",
    )

    tray_test = source / "apps/desktop-tauri/src/surfaces/TrayPanel.test.tsx"
    tray_test_replacements = {
        '''      "Weekly quota",
      "Data status",
      "Actions",''': '''      "Weekly quota",
      "Actions",''',
        'name: /5-hour quota.*42% remaining/i,':
            'name: /5-hour quota.*remaining 42%/i,',
        '''    expect(screen.getByText(/no usage data/i)).toBeInTheDocument();
''': '',
        'screen.getByRole("progressbar", { name: /61% remaining/i })':
            'screen.getByRole("progressbar", { name: /remaining 61%/i })',
        'expect(screen.getAllByRole("region")).toHaveLength(5);':
            'expect(screen.getAllByRole("region")).toHaveLength(4);',
    }
    for old, new in tray_test_replacements.items():
        replace_once(tray_test, old, new, "tray freshness and remaining-copy test")
    replace_once(
        tray_test,
        '''  it("hides the panel from the macOS-style close button without quitting", async () => {
    renderTray();
    await screen.findByRole("button", { name: /profile/i });

    const close = await screen.findByRole("button", {
      name: /hide panel|隐藏面板/i,
    });
    fireEvent.click(close);

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith("dismiss_tray_panel");
    });
    expect(invokeMock).not.toHaveBeenCalledWith("quit_app");
  });

''',
        '',
        "remove obsolete tray close-button test",
    )

    header_test = source / "apps/desktop-tauri/src/surfaces/tray/TrayHeader.test.tsx"
    for old, new in {
        '        productName="codex-barbar"\n        version="1.0.0"\n        profile={\n':
            '        lastUpdatedText="Last updated: 9/9 13:17"\n'
            '        version="1.0.0"\n        profile={\n',
        '        productName="codex-barbar"\n        version="1.0.0"\n        profile={currentCliProfile({':
            '        lastUpdatedText="Last updated: 9/9 13:17"\n'
            '        version="1.0.0"\n        profile={currentCliProfile({',
        '        productName="codex-barbar"\n        version="1.0.0"\n        profile={null}':
            '        lastUpdatedText="Not updated yet"\n'
            '        version="1.0.0"\n        profile={null}',
    }.items():
        replace_once(header_test, old, new, "tray header timestamp test prop")
    replace_once(
        header_test,
        '''    const close = screen.getByRole("button", { name: /hide panel|隐藏面板/i });
    fireEvent.click(close);
    expect(onDismiss).toHaveBeenCalledOnce();
''',
        '''    expect(screen.getByText("Last updated: 9/9 13:17")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pin" })).toBeInTheDocument();
    expect(onDismiss).not.toHaveBeenCalled();
''',
        "tray header pin and timestamp assertions",
    )
    app_test = source / "apps/desktop-tauri/src/App.test.tsx"
    replace_once(
        app_test,
        '      screen.getByRole("heading", { name: "codex-barbar" }),',
        '      screen.getByRole("heading", { name: /尚未更新|not updated yet/i }),',
        "app header freshness assertion",
    )


def patch_taskbar_five_hour_setting(source: Path) -> None:
    settings = source / "rust/src/storage/settings_repository.rs"
    replace_once(
        settings,
        '    pub taskbar_status_enabled: bool,\n    pub float_ball_enabled: bool,',
        '    pub taskbar_status_enabled: bool,\n'
        '    pub taskbar_show_five_hour: bool,\n'
        '    pub float_ball_enabled: bool,',
        "taskbar five-hour setting model",
    )
    replace_once(
        settings,
        '            taskbar_status_enabled: false,\n            float_ball_enabled: true,',
        '            taskbar_status_enabled: false,\n'
        '            taskbar_show_five_hour: true,\n'
        '            float_ball_enabled: true,',
        "taskbar five-hour default",
    )
    replace_once(
        settings,
        '    pub taskbar_status_enabled: Option<bool>,\n    pub float_ball_enabled: Option<bool>,',
        '    pub taskbar_status_enabled: Option<bool>,\n'
        '    pub taskbar_show_five_hour: Option<bool>,\n'
        '    pub float_ball_enabled: Option<bool>,',
        "taskbar five-hour settings patch",
    )
    replace_once(
        settings,
        '        if let Some(value) = patch.taskbar_status_enabled {\n'
        '            self.taskbar_status_enabled = value;\n'
        '        }\n'
        '        if let Some(value) = patch.float_ball_enabled {',
        '        if let Some(value) = patch.taskbar_status_enabled {\n'
        '            self.taskbar_status_enabled = value;\n'
        '        }\n'
        '        if let Some(value) = patch.taskbar_show_five_hour {\n'
        '            self.taskbar_show_five_hour = value;\n'
        '        }\n'
        '        if let Some(value) = patch.float_ball_enabled {',
        "apply taskbar five-hour setting",
    )
    append_once(
        settings,
        "mod plus_taskbar_setting_tests",
        r'''#[cfg(test)]
mod plus_taskbar_setting_tests {
    use super::AppSettings;

    #[test]
    fn missing_taskbar_five_hour_setting_defaults_to_enabled() {
        let mut value = serde_json::to_value(AppSettings::default()).unwrap();
        value.as_object_mut().unwrap().remove("taskbarShowFiveHour");
        let decoded: AppSettings = serde_json::from_value(value).unwrap();
        assert!(decoded.taskbar_show_five_hour);
    }
}''',
    )

    bridge = source / "apps/desktop-tauri/src-tauri/src/commands/bridge.rs"
    replace_once(
        bridge,
        '    pub taskbar_status_enabled: bool,\n    pub float_ball_enabled: bool,',
        '    pub taskbar_status_enabled: bool,\n'
        '    pub taskbar_show_five_hour: bool,\n'
        '    pub float_ball_enabled: bool,',
        "bridge taskbar five-hour dto",
    )
    replace_once(
        bridge,
        '            taskbar_status_enabled: false,\n            float_ball_enabled: false,',
        '            taskbar_status_enabled: false,\n'
        '            taskbar_show_five_hour: true,\n'
        '            float_ball_enabled: false,',
        "bridge taskbar five-hour default",
    )
    replace_once(
        bridge,
        '    pub taskbar_status_enabled: Option<bool>,\n    pub float_ball_enabled: Option<bool>,',
        '    pub taskbar_status_enabled: Option<bool>,\n'
        '    pub taskbar_show_five_hour: Option<bool>,\n'
        '    pub float_ball_enabled: Option<bool>,',
        "bridge taskbar five-hour patch dto",
    )
    replace_once(
        bridge,
        '            taskbar_status_enabled: settings.taskbar_status_enabled,\n'
        '            float_ball_enabled: settings.float_ball_enabled,',
        '            taskbar_status_enabled: settings.taskbar_status_enabled,\n'
        '            taskbar_show_five_hour: settings.taskbar_show_five_hour,\n'
        '            float_ball_enabled: settings.float_ball_enabled,',
        "bridge taskbar five-hour serialization",
    )
    replace_once(
        bridge,
        '            taskbar_status_enabled: self.taskbar_status_enabled,\n'
        '            float_ball_enabled: self.float_ball_enabled,',
        '            taskbar_status_enabled: self.taskbar_status_enabled,\n'
        '            taskbar_show_five_hour: self.taskbar_show_five_hour,\n'
        '            float_ball_enabled: self.float_ball_enabled,',
        "bridge taskbar five-hour patch mapping",
    )
    settings_test = source / "apps/desktop-tauri/src-tauri/src/commands/settings.rs"
    replace_once(
        settings_test,
        '            taskbar_status_enabled: Some(true),\n            float_ball_enabled: Some(false),',
        '            taskbar_status_enabled: Some(true),\n'
        '            taskbar_show_five_hour: Some(false),\n'
        '            float_ball_enabled: Some(false),',
        "settings bridge taskbar five-hour patch test input",
    )
    replace_once(
        settings_test,
        '        assert_eq!(settings.taskbar_status_enabled, Some(true));\n'
        '        assert_eq!(settings.float_ball_enabled, Some(false));',
        '        assert_eq!(settings.taskbar_status_enabled, Some(true));\n'
        '        assert_eq!(settings.taskbar_show_five_hour, Some(false));\n'
        '        assert_eq!(settings.float_ball_enabled, Some(false));',
        "settings bridge taskbar five-hour patch test result",
    )
    replace_once(
        settings_test,
        '        assert!(!dto.taskbar_status_enabled);\n        assert!(dto.float_ball_enabled);',
        '        assert!(!dto.taskbar_status_enabled);\n'
        '        assert!(dto.taskbar_show_five_hour);\n'
        '        assert!(dto.float_ball_enabled);',
        "settings bridge taskbar five-hour dto default test",
    )

    types = source / "apps/desktop-tauri/src/types/bridge.ts"
    replace_once(
        types,
        '  taskbarStatusEnabled: boolean;\n  floatBallEnabled: boolean;',
        '  taskbarStatusEnabled: boolean;\n'
        '  taskbarShowFiveHour?: boolean;\n'
        '  floatBallEnabled: boolean;',
        "typescript taskbar five-hour setting",
    )
    fixtures = source / "apps/desktop-tauri/src/test/profileUsageFixtures.ts"
    replace_once(
        fixtures,
        '  taskbarStatusEnabled: false,\n  floatBallEnabled: false,',
        '  taskbarStatusEnabled: false,\n'
        '  taskbarShowFiveHour: false,\n'
        '  floatBallEnabled: false,',
        "frontend fixture keeps upstream taskbar mode",
    )

    copy = source / "apps/desktop-tauri/src/surfaces/settings/settingsCopy.ts"
    replace_once(
        copy,
        '    taskbarEnabled: string;\n    showIcon: string;',
        '    taskbarEnabled: string;\n    showFiveHour: string;\n    showIcon: string;',
        "taskbar five-hour copy type",
    )
    replace_once(
        copy,
        '    taskbarEnabled: "Show taskbar status",\n    showIcon:',
        '    taskbarEnabled: "Show taskbar status",\n'
        '    showFiveHour: "Show 5H quota in taskbar",\n'
        '    showIcon:',
        "taskbar five-hour English copy",
    )
    replace_once(
        copy,
        '    taskbarEnabled: "显示任务栏状态",\n    showIcon:',
        '    taskbarEnabled: "显示任务栏状态",\n'
        '    showFiveHour: "任务栏显示 5H 额度",\n'
        '    showIcon:',
        "taskbar five-hour Chinese copy",
    )

    tab = source / "apps/desktop-tauri/src/surfaces/settings/tabs/TaskbarTrayTab.tsx"
    replace_once(
        tab,
        '          <label className="settings-switch settings-switch--primary"><input type="checkbox" checked={draft.enabled} disabled={isSavingPreferences || (!draft.enabled && visibleTaskbarItems === 0)} aria-describedby="taskbar-visible-item-help" onChange={(event) => setTaskbarEnabled(event.target.checked)} />{copy.taskbarPresentation.taskbarEnabled}</label>\n'
        '          <div className="settings-preference-grid">',
        '          <label className="settings-switch settings-switch--primary"><input type="checkbox" checked={draft.enabled} disabled={isSavingPreferences || (!draft.enabled && visibleTaskbarItems === 0)} aria-describedby="taskbar-visible-item-help" onChange={(event) => setTaskbarEnabled(event.target.checked)} />{copy.taskbarPresentation.taskbarEnabled}</label>\n'
        '          <label className="settings-switch"><input type="checkbox" checked={settings.taskbarShowFiveHour ?? true} disabled={isSavingPreferences} onChange={(event) => void update({ taskbarShowFiveHour: event.target.checked })} />{copy.taskbarPresentation.showFiveHour}</label>\n'
        '          <div className="settings-preference-grid">',
        "taskbar five-hour settings control",
    )


def patch_taskbar_css(source: Path) -> None:
    path = source / "apps/desktop-tauri/src/surfaces/TaskbarStatus.css"
    append_once(
        path,
        "/* codex-barbar-plus: taskbar dual-quota single row */",
        r'''/* codex-barbar-plus: taskbar dual-quota single row */
.taskbar-status--plus .taskbar-status__main {
  grid-template-columns: none;
  grid-auto-flow: column;
  grid-auto-columns: max-content;
  white-space: nowrap;
}

.taskbar-status--plus .taskbar-status__divider {
  color: var(--quota-unknown);
  font-weight: 700;
  line-height: 1;
}

.taskbar-status--plus .taskbar-status__metric,
.taskbar-status--plus .taskbar-status__reset {
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
    append_once(
        path,
        "/* codex-barbar-plus: resizable scrollable panel */",
        r'''/* codex-barbar-plus: resizable scrollable panel */
html:has(.tray-panel),
html:has(.tray-panel) body,
html:has(.tray-panel) #root {
  height: 100%;
}

.tray-panel.tray-panel--macos {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.tray-panel--macos .tray-panel__header {
  flex: 0 0 auto;
}

.tray-panel--macos .tray-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 2px;
}

.tray-panel--macos .tray-actions {
  flex: 0 0 auto;
}

.tray-panel--macos .tray-scroll::-webkit-scrollbar {
  width: 8px;
}

.tray-panel--macos .tray-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.tray-panel--macos .tray-scroll::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.22);
  border: 2px solid transparent;
  border-radius: 8px;
  background-clip: padding-box;
}''',
    )
    append_once(
        path,
        "/* codex-barbar-plus: header pin toggle */",
        r'''/* codex-barbar-plus: header pin toggle */
.tray-panel--macos .tray-panel__pin svg {
  display: block;
  width: 14px;
  height: 14px;
}

.tray-panel--macos .tray-panel__pin[data-pinned="true"] {
  color: var(--tray-accent);
  background: rgba(48, 209, 88, 0.16);
  border-color: rgba(48, 209, 88, 0.5);
}

.tray-panel--macos .tray-panel__pin[data-pinned="true"]:hover {
  color: var(--tray-accent);
  background: rgba(48, 209, 88, 0.26);
  border-color: rgba(48, 209, 88, 0.65);
  transform: scale(1.04);
}

[data-theme="light"] .tray-panel--macos .tray-panel__pin[data-pinned="true"] {
  background: rgba(36, 138, 61, 0.12);
  border-color: rgba(36, 138, 61, 0.4);
}

[data-theme="light"] .tray-panel--macos .tray-panel__pin[data-pinned="true"]:hover {
  background: rgba(36, 138, 61, 0.2);
  border-color: rgba(36, 138, 61, 0.55);
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

    for package_name in ("codexbar", "codex-barbar-desktop"):
        replace_once(
            source / "Cargo.lock",
            f'name = "{package_name}"\nversion = "1.0.30"',
            f'name = "{package_name}"\nversion = "{version}"',
            f"{package_name} lockfile package version",
        )

    # The Plus version has its own numbering (0.2.0). Upstream's hard-coded
    # 1.0.0 fixture is newer than this release, so use an actually older tag.
    replace_once(
        source / "rust/src/update_check.rs",
        'r#"{"tag_name":"v1.0.0","html_url":"https://github.com/naipi11/codex-barbar/releases/tag/v1.0.0"}"#',
        'r#"{"tag_name":"v0.0.0","html_url":"https://github.com/naipi11/codex-barbar/releases/tag/v0.0.0"}"#',
        "older release fixture for Plus version numbering",
    )


def patch_portable_docs(source: Path) -> None:
    path = source / "PORTABLE.md"
    replace_once(
        path,
        "```text\n"
        "codex-barbar.exe\n"
        "LICENSE\n",
        "```text\n"
        "codex-barbar.exe\n"
        "WebView2Loader.dll\n"
        "LICENSE\n",
        "portable WebView2 loader file list",
    )
    replace_once(
        path,
        "No installer or registry change is made. The executable is the same\n"
        "Windows x64 desktop binary that the NSIS installer deploys.\n",
        "No installer or registry change is made. `WebView2Loader.dll` is the x64\n"
        "runtime loader produced beside the executable and must remain in the same\n"
        "directory. The executable is the same Windows x64 desktop binary that the\n"
        "NSIS installer deploys.\n",
        "portable WebView2 loader guidance",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--version", default="0.2.0")
    args = parser.parse_args()

    source = args.source.resolve()
    overlay = args.overlay.resolve()
    if not (source / "apps/desktop-tauri/src-tauri/tauri.conf.json").is_file():
        raise RuntimeError(f"not a codex-barbar checkout: {source}")

    copy_overrides(overlay, source)
    patch_tauri_bridge(source)
    patch_flyout(source)
    patch_dwm_resize_frame(source)
    patch_tauri_window(source)
    patch_window_default_size(source)
    patch_styles_css(source)
    patch_window_commands(source)
    patch_main(source)
    patch_notification_controller(source)
    patch_notification_labels(source)
    patch_reset_notification_sound_storage(source)
    patch_reset_notification_sound_bridge(source)
    patch_reset_notification_sound_controller(source)
    patch_reset_notification_sound_ui(source)
    patch_freshness_setting(source)
    patch_taskbar_five_hour_setting(source)
    patch_taskbar_css(source)
    patch_task_css(source)
    patch_audit_usage(source)
    patch_audit_ui(source)
    patch_audit_settings(source)
    patch_memory_fixes(source)
    patch_version_branding(source, args.version)
    patch_portable_docs(source)
    print(f"codex-barbar-plus overlay applied ({args.version})")


if __name__ == "__main__":
    main()
