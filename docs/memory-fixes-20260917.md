# Background UI memory fixes — 1.0.30-plus.7

## Changes

- Usage statistics cache at most eight `Intl.DateTimeFormat` instances (two
  supported locales and four styles), instead of creating one per heatmap day
  on every render. React memoization skips unrelated parent quota updates.
- Settings' native close and Escape destroy the auxiliary WebView. The main
  tray host remains alive, so this does not exit the application. Opening
  Settings again creates a fresh page on the requested tab.
- The main tray mounts its dashboard only while visible. Hiding it cleans up
  dashboard subscriptions, pending bootstrap updates and the elapsed-time timer.
  Showing it obtains a fresh bootstrap/task snapshot. A revision guard prevents
  an old visibility query from undoing a newer show/hide event.
- The taskbar renders its inert width-measurement replica in its own document,
  sharing state and subscriptions. The separate measurement WebView, creation
  retries, destruction handlers, frontend route and permission label were removed.
  Only the enabled visible taskbar can submit measured widths; existing width
  clamping, deduplication and resize rollback remain.
- Updated one stale geometry test: the existing 580 CSS-pixel default height is
  1160 physical pixels at 200% scaling, not the old 940. Window dimensions were
  not changed by this release.

The persistent implementation is `scripts/memory-fixes.patch`, applied by
`scripts/memory_fixes.py` after the existing Plus patches in `apply_plus.py`.
The default build version is now Plus.7. Generated `upstream/` is not the sole
copy of these changes.

## Verification

- Frontend: **44 test files, 325 tests passed**; TypeScript and production Vite
  build passed. Coverage includes bounded formatter allocation, skipped unrelated
  renders, visibility races, unmount cleanup, same-page width measurement and
  width-observer disconnection.
- Tauri shell: **259 tests passed**.
- Shared Rust library: **489 passed, 1 failed, 1 ignored**. The failure is
  `update_check::tests::same_or_older_release_is_current`: the existing updater
  rejects the `plus.N` suffix and compares against its fallback version. The
  identical test was rerun against the previous Plus.6 source and failed there
  too. Updater behavior was not changed in this memory-focused release.
- `cargo fmt --all --check` passed. Strict Clippy was run for both manifests and
  remains blocked by pre-existing lints in `cost_scanner.rs`, `desktop_tasks.rs`,
  `notification_controller.rs` and `shell/dwm.rs`. No clean Clippy claim is made.
- Extracted a fresh v1.0.30 tree, applied the full overlay successfully, and
  compared **941 files with zero mismatches**, normalizing UTF-8 BOM/line endings.
  Generated `Cargo.lock` was excluded from this source comparison.
- Windows production EXE built with the Tauri CLI and the existing Rust 1.90.0 /
  LLVM-MinGW toolchain, using embedded frontend assets. The portable includes
  the matching x64 `WebView2Loader.dll`.

## Actual Windows observations

Using Computer Use on the newly built EXE:

- About shows `1.0.30-plus.7`; the settings layout and real local usage statistics
  loaded correctly, including the 365-day accessible heatmap.
- Closing Settings with the native close button removed renderer PID 33092 while
  main PID 50688 and its other two renderers remained alive.
- Reopening Settings created renderer PID 51604. Pressing Escape removed that
  renderer as well, without exiting the host.
- The tray could be shown again with current quota and the ongoing task intact.
- While the statistics page remained open, its private working set was 26.0 MiB
  at 12:09:26 and 26.2 MiB at 12:10:21; private commit was 36.7 and 37.0 MiB.
  These are short observations, not a long-duration leak test.

WebView2 automatically changed from 152.0.4191.66 in the old long-running process
to 153.0.4234.32 on the new cold launch. Therefore before/after total-memory values
are not a controlled estimate of the code's savings. The old large renderer was
not heap-profiled, as requested. Independent taskbar pixel capture and multi-DPI /
multi-monitor acceptance remain unverified: Computer Use exposes the tray and
Settings windows, but not the taskbar tool window. Width logic is regression-tested
and the extra measurement process is no longer created.

Logs and source-comparison details are under `artifacts/memory-fixes/`.

## Installed result

The verified EXE was copied into the existing portable location
`D:\Apps 2\codex-barbar-plus_1.0.30-plus.6_x64-portable\codex-barbar.exe`.
The directory name is retained so the existing autostart entry still works;
the executable and visible UI are version **1.0.30-plus.7**. The previous EXE
and README are backed up in `artifacts/memory-fixes/original-portable/`.
The loader DLL already matched, so it was not replaced.

The installed normal-mode process was visually checked with the real account
and current task, then returned to the background. At 12:14:32 the host plus
WebView2 group had **8 processes, 2 renderers, 198.6 MiB private working set**
and 277.0 MiB private commit. This is a cold-start observation, not a sustained
memory ceiling or a controlled comparison to the old process.

Verified EXE SHA-256:
`29fa86bb04f1674fe656cbfacad5dfb99d4b528f8e2109694a73b43b1f1af538`.
Original backed-up EXE SHA-256:
`ab7472df8c45a7c3d5d2ddae2bfcab3fa57fb4d24ccd23f7db268c68814210df`.
