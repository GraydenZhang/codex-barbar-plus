# v0.2.0：Codex Desktop 最大化时任务栏状态条消失

日期：2026-10-29（Asia/Shanghai）。

## 问题与原因

Codex Desktop 使用自定义标题栏。实机最大化窗口的 Win32 样式为
`0x15070000`，不包含 `WS_CAPTION`。旧 `fullscreen_guard.rs` 将“没有系统标题栏、
覆盖工作区”的窗口判为全屏。工作区不包含任务栏，因此普通最大化被误判，随后
`status_surfaces` 按现有“全屏隐藏”设置隐藏任务栏状态条。

本机复现时（物理像素、200% 缩放）：

| 对象 | left | top | right | bottom |
|---|---:|---:|---:|---:|
| Codex 所在显示器 | 3840 | 248 | 6912 | 2168 |
| 显示器工作区 | 3840 | 248 | 6912 | 2072 |
| 最大化的 Codex 窗口 | 3840 | 248 | 6912 | 2072 |

旧程序的任务栏状态窗口在 Codex 最大化且位于前台时为 `visible=false`；
通过原生“恢复”按钮退出最大化后，Codex 的 `maximized=false`，状态条恢复为
`visible=true`。证据保存在 `artifacts/verification/before-*.json`。

## 修复

顶层窗口与浏览器渲染窗口均须覆盖完整显示器才视为全屏；移除以 `WS_CAPTION`
和工作区覆盖推断全屏的分支。保留原来的 8 个物理像素容差、真正全屏时隐藏、
退出全屏恢复、前台切换和周期检查。没有对 Codex 进程名或标题做白名单。

逐帧检查还发现：最大化切换瞬间，`Intermediate D3D Window` 子窗口一度为
`[3840, 248, 7168, 2552]`，超过其工作区大小的父窗口。旧渲染扫描直接使用子窗口
原始矩形，产生一次额外误判。最终实现先将子窗口矩形与顶层宿主矩形求交，再判断
是否覆盖显示器，避免将被父窗口裁剪的 GPU 区域当成真正全屏。

持久实现位于
`overrides/apps/desktop-tauri/src-tauri/src/shell/fullscreen_guard.rs`；
`scripts/apply_plus.py` 会将它应用到干净的上游 v1.0.30 源码。

新增回归覆盖：本机实际窗口坐标、无边框最大化的不可见调整边框、负坐标显示器、
四个任务栏方向、GPU 子窗口溢出宿主，以及真正覆盖显示器的全屏窗口。

## 源码基线与恢复

GitHub Plus 仓库基线为 `fe45af1`，上游 v1.0.30 的提交为
`2bd3671f3b171b38cc346aea2e88c4766f154d96`。
本机原 portable 目录名仍含 plus.6，但 EXE 的实际文件版本为 `1.0.30-plus.7`。
GitHub 尚未包含这些本机后续修复，因此从本机 2026-09-09、09-12、09-17 的历史
源代码补丁恢复通知声音、任务跟踪、设置交互及 Plus.7 内存优化，再实施本次修复。
恢复后的持久代码在 `scripts/`、`overrides/`；完整生成源码在 `upstream/`。
旧修复的历史说明保留在另外两份 docs 中，其中的旧测试结果不代替本次验证。

产品、Cargo、Tauri 和前端版本统一为 `0.2.0`。为适应独立 Plus 版本编号，更新
检查的一条测试数据从 `v1.0.0` 改为真正更旧的 `v0.0.0`；更新检查运行逻辑未改动。

## 验证

- 前端：44 个测试文件、325 项测试通过；TypeScript 和 Vite 生产构建通过。
- 全屏判断的独立回归验证：旧实现对实际 Codex 坐标和 GPU 子窗口坐标的
  两项新增断言失败（预期）；修复后 16 项判断测试，以及 1 项读取当前实机
  Codex 最大化窗口及其渲染窗口的原生扫描测试通过。
  该独立验证仅移除 serde 序列化标记以单独编译模块，
  几何判断和 Win32 调用保持原样；完整 Tauri 集成另行测试。
- Rust workspace：共享库 490 项、集成测试 17 + 3 项通过；最终桌面端重新测试
  263 项通过，合计 773 项通过、1 项原有测试忽略。`cargo fmt --all --check` 通过。
- 干净 v1.0.30 解包后重新应用完整 overlay，再格式化，与实际构建源码逐文件比较：
  **942 个文件，0 个差异**，包括 Cargo.lock；依赖版本未改变。
- Tauri CLI `tauri build --no-bundle -- --offline` 的 Windows x64 release 构建通过。
  EXE 文件和产品版本均为 `0.2.0`，前端资源已嵌入，无需本地开发服务器。
- 实机初版：启动后 Codex 保持最大化，5 次采样状态条可见；退出最大化后
  3 次采样可见；再次最大化并处于前台时，第一帧发现 GPU 子窗口导致的短暂隐藏，
  随后 2 次稳态采样可见。可见采样的窗口中心均命中状态条自身，未被其他窗口遮住。
  因此又补充了上述宿主裁剪修复，未将初版的切换采样全部宣称通过。
- 最终源码的只读原生实机测试：对仍处于最大化的 Codex 真实 HWND，确认窗口等于
  工作区且不等于显示器；直接执行最终实现的顶层窗口与全部同进程渲染窗口扫描，
  均未误判全屏。最大化动画不能在电脑操作工具中止后重新操作，最终动画行为由
  已捕获坐标的回归用例验证。
- 最终 release EXE 替换原运行目录后重新启动，3 次一秒间隔采样中任务栏状态条
  均可见，窗口中心均命中自身；安装文件的 SHA-256 与构建文件一致。
- 电脑操作工具操作了 Codex 的原生恢复/最大化按钮；任务栏工具窗口无法由该工具
  单独截图，因此任务栏部分使用只读 Win32 可见性、位置和命中检测作为证据。
  诊断脚本不会读取标题、网页内容、账户或令牌。
- 真正浏览器全屏的实机隐藏/恢复：**NOT_RUN**。选择浏览器时，电脑操作工具因
  无法可靠确认浏览器 URL 而中止。没有绕过该限制；全屏判断仅有上述代码回归证明。
  其他窗口的最大化，以及其它 DPI/任务栏方向组合，未做本次实机操作验证。
- 严格 Clippy（两个 manifest 的 `--all-targets -- -D warnings`）：**FAIL**，
  被恢复基线 `rust/src/storage/settings_repository.rs:102` 中手写的
  `NotificationSound::default` 的 `clippy::derivable_impls` 告警阻塞。
  该实现来自原通知声音功能，未作为本次窗口修复的一部分改写。

本次证据在 `artifacts/verification/`：`cargo-test.log`、`frontend-test.log`、
`frontend-build.log`、`tauri-release-final-build.log`、`source-comparison.json`、
`fullscreen-red.log`、`fullscreen-green.log`、`before-*.json` 和 `after-*.json`。
`fullscreen-fix-v0.2.0.patch` 是单独的本次全屏判断差异，便于区分历史源码恢复。

## 本机替换与回退

新版已替换并从原路径重新启动：
`D:\Apps 2\codex-barbar-plus_1.0.30-plus.6_x64-portable\codex-barbar.exe`。
目录名称保留，以沿用原有启动路径；其中 EXE 实际版本为 `0.2.0`。
没有修改账户、设置或自启动配置。原 EXE 和 README 位于
`artifacts/original-portable/`；回退时先退出程序，再将备份 EXE 复制回原位置。

新 EXE 的 SHA-256：
`2cb9b03f531762798e9aee30898cd9112d75afde21fa449207f8b4a41aa06ccf`。
原 EXE 的 SHA-256：
`29fa86bb04f1674fe656cbfacad5dfb99d4b528f8e2109694a73b43b1f1af538`。
WebView2Loader.dll 的新旧 SHA-256 相同。

本次原生构建使用 Windows x64 GNU 工具链、Rust 1.98.1、Node 24.14.0 和本机
已有 pnpm 11.25.0，未安装额外工具或添加项目依赖。前端使用原有 lockfile。
上游 CI 使用 MSVC，因此本机 GNU 构建与 CI 工具链有差异。

Win32 边框参考：微软说明 GetWindowRect 可能包含不可见调整边框：
<https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowrect>。

## 本地构建与使用

1. 在项目根目录将上游 v1.0.30 克隆到 `upstream/`。
2. 执行 `python scripts/apply_plus.py --source upstream --overlay .`。
3. 安装 lockfile 中现有前端依赖，执行前端测试及 `cargo test --workspace`。
4. 执行 `./scripts/build-portable.ps1`。脚本通过 Tauri CLI 嵌入生产前端，
   使用 `--no-bundle` 生成 portable 所需 EXE，并按固定清单打包。

Portable 文件夹内直接运行 `codex-barbar.exe`，`WebView2Loader.dll` 必须与 EXE 同目录。
设置、账户和缓存继续使用原程序的数据目录，portable 包不携带这些用户数据。
源码恢复时使用的原始聊天记录仅作为临时输入，不随 portable 发布。
临时源码和历史记录副本已移至本机 Codex 临时缓存；交付目录保留本次检查证据、
最终 portable 和原程序备份。ZIP 按固定的 11 个文件白名单检查，账户、缓存和
设置文件不在打包清单中。
