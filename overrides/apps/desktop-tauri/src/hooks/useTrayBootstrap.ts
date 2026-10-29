import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { events, getBootstrapState } from "../lib/tauri";
import type { AppSettingsDto, BootstrapDto } from "../types/bridge";

export function useTrayBootstrap() {
  const [bootstrap, setBootstrap] = useState<BootstrapDto | null>(null);
  const [bootstrapError, setBootstrapError] = useState(false);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | undefined;
    let latestSettings: AppSettingsDto | null = null;

    const load = async () => {
      try {
        const stop = await listen<AppSettingsDto>(events.settingsChanged, ({ payload }) => {
          if (!active) return;
          latestSettings = payload;
          // Settings must not reload stale account selection or usage caches.
          setBootstrap((current) => current ? { ...current, settings: payload } : current);
        });
        if (!active) {
          stop();
          return;
        }
        unlisten = stop;
      } catch {
        // The initial snapshot remains useful if event registration is unavailable.
      }
      if (!active) return;
      try {
        const initial = await getBootstrapState();
        if (active) {
          // An event received while loading is newer than the pending snapshot.
          setBootstrap(latestSettings ? { ...initial, settings: latestSettings } : initial);
        }
      } catch {
        if (active) setBootstrapError(true);
      }
    };
    void load();
    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  return { bootstrap, bootstrapError };
}
