# codex-barbar-plus 1.0.30-plus.1

This portable build is based on `naipi11/codex-barbar` v1.0.30 and keeps the
original codex-barbar UI and Windows/Tauri shell.

Plus additions:

- taskbar: 5-hour quota + reset clock, weekly quota + reset date, no account name
- tray panel: Pin / 置顶 button
- Codex Desktop local task status (working / ready for review / needs attention)
- multi-task tracking and long-task completion notification sound
- confirmed 5-hour + weekly reset notifications with sound

Quota reset detection uses the actual local codex-barbar app-server snapshots.
It does not simply fire a timer at the displayed reset time.
