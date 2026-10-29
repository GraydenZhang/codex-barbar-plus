"""Checked UI fixes applied after the regular Plus transformations."""

from pathlib import Path


def _replace(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{path}: expected {count} UI anchors, found {actual}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def apply(source: Path) -> None:
    src = source / "apps/desktop-tauri/src"
    selector = src / "surfaces/tray/ProfileSelector.tsx"
    for condition in ['event.key === "Escape" && open', 'event.key === "Escape"']:
        _replace(
            selector,
            f'}} else if ({condition}) {{\n      event.preventDefault();\n      close();',
            f'}} else if ({condition}) {{\n      event.preventDefault();\n      event.stopPropagation();\n      close();',
        )

    settings = src / "surfaces/Settings.tsx"
    _replace(settings, 'import { useEffect, useState } from "react";',
             'import { useEffect, useLayoutEffect, useRef, useState } from "react";')
    _replace(settings, '  const [tab, setTab] = useState<SettingsTabId>(initialTab);',
             '  const [tab, setTab] = useState<SettingsTabId>(initialTab);\n'
             '  const paneRef = useRef<HTMLDivElement>(null);\n'
             '  useLayoutEffect(() => {\n'
             '    if (paneRef.current) paneRef.current.scrollTop = 0;\n'
             '  }, [tab]);')
    _replace(settings, '<div className="settings-panel__pane">',
             '<div ref={paneRef} className="settings-panel__pane">')

    general = src / "surfaces/settings/tabs/GeneralTab.tsx"
    _replace(general,
             '<label>\n          <input type="checkbox" checked={settings.autostartEnabled}',
             '<label className="settings-switch">\n'
             '          <input type="checkbox" checked={settings.autostartEnabled}')

    spend = src / "surfaces/settings/tabs/UsageSpendTab.tsx"
    _replace(spend, 'import { getUsageSpend } from "../../../lib/tauri";',
             'import { getUsageSpend } from "../../../lib/tauri";\n'
             'import { resolveLanguage } from "../../../lib/resolveLanguage";')
    _replace(spend, 'language === "zh-CN" ? "zh-CN" : "en-US"',
             'resolveLanguage(language)', count=4)
    _replace(spend, 'const chinese = language === "zh-CN";',
             'const chinese = resolveLanguage(language) === "zh-CN";')
