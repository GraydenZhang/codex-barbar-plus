# codex-barbar-plus

Personal Windows enhancements built **on top of `naipi11/codex-barbar` v1.0.30**.
The overlay intentionally preserves the upstream Tauri/React/Rust shell and its
existing visual design rather than reimplementing the app.

## Changes

- Taskbar capsule keeps the original design but removes the account name.
- Taskbar shows the **5-hour quota + its local reset time** and the **weekly quota + reset date**.
- Tray panel adds a **Pin / 置顶** button. Pinning prevents the panel from auto-hiding when it loses focus; all other upstream window behavior is retained.
- Reads local Codex Desktop session JSONL files under `%USERPROFILE%\.codex\sessions` and shows compact task state only while there are relevant tasks:
  - Working / 工作中
  - Ready for review / 完成待查看
  - Needs attention / 需要检查
- Tracks multiple active/recent Desktop turns and local task duration.
- Long Codex Desktop tasks (3 minutes or more) use the existing Windows notification/sound path when they finish.
- Adds confirmed **5-hour and weekly quota reset** notifications. Detection requires the rate-limit window to advance and either the old deadline to have elapsed or allowance to visibly recover, which avoids treating a simple `resetAt` correction as a real reset.
- Reset baseline is persisted by upstream `codex-barbar`, so a reset that happens during sleep can be recognized after wake on the next successful usage refresh.

## Build

GitHub Actions clones the exact upstream `v1.0.30` tag, applies the focused overlay, type-checks the frontend, checks the Rust workspace, builds the native Tauri Windows app, and uploads a portable x64 ZIP.

Upstream license and notices are preserved in the portable package.
