# September 12 audit fixes — 1.0.30-plus.6

Before implementation, the Plus project was saved at `57a1d00`; the pre-existing
generated upstream source was separately preserved at `f949835` in its local Git
repository. Existing portable packages were kept intact.

Persistent fixes live in `overrides/` and the checked `scripts/audit_*.py` patches,
which `scripts/apply_plus.py` applies to upstream tag `v1.0.30`. The generated
`upstream/` checkout is not the source of the fixes.

## Changes

1. Token totals use input plus output; cached input remains a reported subset.
   Summary, model, and daily totals agree without changing the cost calculation.
2. Escape dismisses an open account dropdown before dismissing the tray.
3. Switching settings categories resets the content scroll position.
4. The autostart checkbox and its label share a vertically centered layout.
5. System-language resolution is consistent for dates and Plus UI text.
6. Settings events update an existing tray without discarding account selection
   or newer usage data.
7. Task tracking recovers a running turn whose start lies beyond the initial
   tail-read window.
8. Incomplete or temporarily unreadable session metadata is retried.
9. Threshold inputs retain drafts and validate/commit on blur or Enter.
10. Five-hour quota and account visibility work independently; five-hour quota
    counts toward the minimum visible taskbar content.
11. A failed sound preview is distinguished from a failed settings save.

## Verification

- Frontend: **44 files / 328 tests passed**; TypeScript and Vite production build
  passed.
- Rust: **45 relevant tests passed** (8 usage aggregation, 24 settings storage,
  13 task tracking). This is the relevant regression suite, not a claim that every
  unrelated upstream Rust test was run.
- Reproducibility: applied the overlay to a second clean `v1.0.30` worktree and
  compared 942 listed source files. All compared contents matched; `Cargo.lock`
  was excluded because Cargo updates local package versions during compilation.
- Windows x64 release built using the existing Rust 1.90.0 GNU/LLVM-MinGW toolchain.
  Portable staging includes the same-directory x64 `WebView2Loader.dll`.

Actual Windows UI verification on the new executable:

- Version label displays `1.0.30-plus.6`; a running 18-minute task survived the
  application restart and was recovered in the tray.
- Escape closes the account dropdown while keeping the tray visible.
- The autostart checkbox and label are vertically aligned.
- Switching from remaining to used immediately changes the already-open tray.
- Entering `5`, then `0`, leaves the stored warning threshold at `66` while editing;
  Enter commits `50`. The original `66` was then restored.
- Switching from the notification page bottom to taskbar settings shows the top
  of the new page.
- In system Chinese mode, dates display in Chinese. The usage panel showed
  input `4.33亿`, cached input `4.19亿`, output `173.51万`, and total `4.35亿`,
  consistent with input plus output after display rounding.
- The settings record and selected profile exactly match the pre-test snapshot
  after restoring temporary changes. The original pinned tray state was restored.

Incomplete-file races, failed-save/failed-preview cases, and the five-hour/account
visibility combinations were verified by regression tests. The native taskbar
capsule itself, multiple-monitor/DPI combinations, and audio listening were not
separately verified in this run.
