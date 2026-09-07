import { Fragment } from "react";
import type { TrayCopy } from "./copy";

const ACTION_IDS = ["refresh", "open_usage", "settings", "dismiss", "quit"] as const;

interface TrayActionsProps {
  copy: TrayCopy;
  order?: readonly string[];
  onRefresh(): Promise<void> | void;
  onOpenUsage(): Promise<void> | void;
  onOpenSettings(): Promise<void> | void;
  onDismiss(): Promise<void> | void;
  onQuit(): Promise<void> | void;
  pinned?: boolean;
  onTogglePin?(): Promise<void> | void;
  pinLabel?: string;
  unpinLabel?: string;
  autoFocusRefresh?: boolean;
}

export default function TrayActions({
  copy,
  order = ACTION_IDS,
  onRefresh,
  onOpenUsage,
  onOpenSettings,
  onDismiss,
  onQuit,
  pinned = false,
  onTogglePin = () => {},
  pinLabel = "Pin",
  unpinLabel = "Unpin",
  autoFocusRefresh = false,
}: TrayActionsProps) {
  const visible = order.filter((id): id is (typeof ACTION_IDS)[number] =>
    ACTION_IDS.includes(id as (typeof ACTION_IDS)[number]),
  );
  const pinButton = (
    <button
      key="pin"
      type="button"
      data-pinned={pinned ? "true" : "false"}
      aria-pressed={pinned}
      onClick={() => void onTogglePin()}
    >
      {pinned ? unpinLabel : pinLabel}
    </button>
  );

  return (
    <section className="tray-region tray-actions" role="region" aria-label={copy.actions}>
      <h2>{copy.actions}</h2>
      <div className="tray-actions__buttons tray-actions__buttons--single">
        {visible.map((id) => {
          let action: JSX.Element | null = null;
          switch (id) {
            case "refresh":
              action = (
                <button type="button" autoFocus={autoFocusRefresh} onClick={() => void onRefresh()}>
                  {copy.refresh}
                </button>
              );
              break;
            case "open_usage":
              action = (
                <button type="button" onClick={() => void onOpenUsage()}>
                  {copy.openUsage}
                </button>
              );
              break;
            case "settings":
              action = (
                <button type="button" onClick={() => void onOpenSettings()}>
                  {copy.settings}
                </button>
              );
              break;
            case "dismiss":
              action = (
                <button type="button" onClick={() => void onDismiss()}>
                  {copy.dismiss}
                </button>
              );
              break;
            case "quit":
              action = (
                <button type="button" onClick={() => void onQuit()}>
                  {copy.quit}
                </button>
              );
              break;
          }
          return (
            <Fragment key={id}>
              {action}
              {id === "settings" ? pinButton : null}
            </Fragment>
          );
        })}
        {!visible.includes("settings") ? pinButton : null}
      </div>
    </section>
  );
}
