# codex-barbar-plus v0.2.0

This portable build is based on `naipi11/codex-barbar` v1.0.30 and keeps the
original codex-barbar UI and Windows/Tauri shell.

v0.2.0 fixes the taskbar status disappearing when Codex Desktop is maximized.
Fullscreen detection now requires coverage of the complete monitor, including
the taskbar area. Borderless windows covering only the work area remain visible.
Actual fullscreen applications still suspend the status surface when enabled.
See `docs/fix-maximized-taskbar-v0.2.0.md` for reproduction and validation.

This build retains the Plus.7 background UI memory fixes: date formatters are reused, unchanged usage
statistics skip quota-driven renders, closing Settings destroys its WebView,
the hidden tray unmounts its dashboard, and taskbar width measurement shares the
visible taskbar's WebView. Background quota refresh and task notifications remain
in Rust. See `docs/memory-fixes-20260917.md` for validation and its limits.

Plus additions:

- taskbar: optional 5-hour quota + reset clock, weekly quota + reset date,
  and account name controlled by its own setting
- tray panel: Pin / 置顶 button
- Codex Desktop local task status (working / ready for review / needs attention)
- multi-task tracking and long-task completion notification sound
- confirmed 5-hour + weekly reset notifications with sound

Quota reset detection uses the actual local codex-barbar app-server snapshots.
It does not simply fire a timer at the displayed reset time.

This release corrects cached-token double counting, settings synchronization,
long-task recovery, incomplete session discovery, notification threshold editing,
sound-preview error reporting, and the visual/keyboard issues found in the
September 12 audit. See `docs/audit-fixes-20260912.md` for verification details.
