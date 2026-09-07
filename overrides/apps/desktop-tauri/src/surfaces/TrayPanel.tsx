import { useEffect, useMemo, useState } from "react";
import {
  dismissTrayPanel,
  getBootstrapState,
  getFlyoutPinned,
  openCodexUsagePage,
  openSettingsWindow,
  quitApp,
  setFlyoutPinned,
} from "../lib/tauri";
import type { BootstrapDto } from "../types/bridge";
import { useDesktopTasks } from "../hooks/useDesktopTasks";
import { useProfileUsage } from "../hooks/useProfileUsage";
import { useTheme } from "../hooks/useTheme";
import DesktopTaskStatus from "./tray/DesktopTaskStatus";
import ProfileSelector from "./tray/ProfileSelector";
import QuotaCard from "./tray/QuotaCard";
import TrayActions from "./tray/TrayActions";
import TrayHeader from "./tray/TrayHeader";
import UsageStatus from "./tray/UsageStatus";
import { trayCopy } from "./tray/copy";
import "./tray/TrayPanel.css";

function systemTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function TrayDashboard({ bootstrap }: { bootstrap: BootstrapDto }) {
  const usage = useProfileUsage(bootstrap);
  const desktopTasks = useDesktopTasks();
  useTheme(bootstrap.settings.theme);
  const language = bootstrap.settings.language;
  const copy = useMemo(() => trayCopy(language), [language]);
  const locale =
    language === "zh-CN"
      ? "zh-CN"
      : language === "en-US"
        ? "en-US"
        : navigator.language || "en-US";
  const timeZone = systemTimeZone();
  const panel = bootstrap.settings.panel;
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    let active = true;
    void getFlyoutPinned()
      .then((value) => {
        if (active) setPinned(value);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const togglePin = async () => {
    const next = !pinned;
    const applied = await setFlyoutPinned(next);
    setPinned(applied);
  };

  const selectedProfile = usage.profiles.find(
    (profile) => profile.id === usage.selectedProfileId,
  );
  const primary = usage.state.primary;
  const secondary = usage.state.secondary;
  const zh = language !== "en-US";

  return (
    <main
      className={`tray-panel tray-panel--macos tray-panel--${panel.density}`}
      data-density={panel.density}
      aria-label="codex-barbar tray panel"
    >
      <TrayHeader
        productName="codex-barbar"
        version={bootstrap.version}
        profile={selectedProfile ?? null}
        copy={copy}
        showAccountStatus={panel.showAccountStatus}
        onDismiss={dismissTrayPanel}
      />

      <div className="tray-stack">
        <ProfileSelector
          profiles={usage.profiles}
          selectedProfileId={usage.selectedProfileId}
          copy={copy}
          onSelect={usage.selectProfile}
          autoFocus={usage.profiles.length > 0}
        />

        {primary ? (
          <QuotaCard
            window={primary}
            displayMode={bootstrap.settings.displayMode}
            copy={copy}
            locale={locale}
            timeZone={timeZone}
            showResetTime={panel.showResetTime}
          />
        ) : null}
        {secondary ? (
          <QuotaCard
            window={secondary}
            displayMode={bootstrap.settings.displayMode}
            copy={copy}
            locale={locale}
            timeZone={timeZone}
            showResetTime={panel.showResetTime}
          />
        ) : null}

        <DesktopTaskStatus snapshot={desktopTasks} language={language} />
      </div>

      <UsageStatus
        state={usage.state}
        isSwitching={usage.isSwitching}
        copy={copy}
        locale={locale}
        showFreshness={panel.showFreshness}
        onRefresh={usage.refresh}
        onOpenSettings={openSettingsWindow}
        onOpenUsage={openCodexUsagePage}
      />

      <TrayActions
        copy={copy}
        order={panel.actions.order}
        onRefresh={usage.refresh}
        onOpenUsage={openCodexUsagePage}
        onOpenSettings={openSettingsWindow}
        onDismiss={dismissTrayPanel}
        onQuit={quitApp}
        pinned={pinned}
        onTogglePin={togglePin}
        pinLabel={zh ? "置顶" : "Pin"}
        unpinLabel={zh ? "取消置顶" : "Unpin"}
        autoFocusRefresh={usage.profiles.length === 0}
      />

      {selectedProfile ? (
        <span className="sr-only" aria-live="polite">
          {selectedProfile.presentationName}
        </span>
      ) : null}
    </main>
  );
}

export default function TrayPanel() {
  const [bootstrap, setBootstrap] = useState<BootstrapDto | null>(null);
  const [bootstrapError, setBootstrapError] = useState(false);

  useEffect(() => {
    let active = true;
    getBootstrapState()
      .then((state) => {
        if (active) setBootstrap(state);
      })
      .catch(() => {
        if (active) setBootstrapError(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        void dismissTrayPanel();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  if (!bootstrap) {
    return (
      <main className="tray-panel tray-panel--macos" aria-label="codex-barbar tray panel">
        <TrayHeader
          productName="codex-barbar"
          version="…"
          profile={null}
          copy={trayCopy("system")}
          onDismiss={dismissTrayPanel}
        />
        <p role={bootstrapError ? "alert" : undefined}>
          {bootstrapError ? "Unable to load CodexBar state." : "Loading…"}
        </p>
      </main>
    );
  }

  return <TrayDashboard bootstrap={bootstrap} />;
}
