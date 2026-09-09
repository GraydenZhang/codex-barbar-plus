import { getCurrentWindow } from "@tauri-apps/api/window";
import { setFlyoutInteracting } from "../../lib/tauri";
import type { ProfileSummaryDto } from "../../types/bridge";
import { profileDisplayName } from "../../hooks/useStatusSurface";
import AccountAvatar from "../../components/AccountAvatar";
import type { TrayCopy } from "./copy";

interface TrayHeaderProps {
  lastUpdatedText: string;
  version: string;
  profile: ProfileSummaryDto | null;
  copy: TrayCopy;
  showAccountStatus?: boolean;
  onDismiss(): Promise<void> | void;
  pinned?: boolean;
  onTogglePin?(): Promise<void> | void;
  pinLabel?: string;
  unpinLabel?: string;
}

export default function TrayHeader({
  lastUpdatedText,
  version,
  profile,
  copy,
  showAccountStatus = true,
  pinned = false,
  onTogglePin = () => {},
  pinLabel = "Pin",
  unpinLabel = "Pinned",
}: TrayHeaderProps) {
  const identity = profileDisplayName(profile);
  const secondary = !profile
    ? copy.signedOut
    : profile.accountStatus === "signedIn"
      ? copy.signedIn
      : profile.accountStatus === "signedOut"
        ? copy.signedOut
        : copy.accountUnavailable;

  const beginDrag = () => {
    void setFlyoutInteracting(true).catch(() => undefined);
    void getCurrentWindow().startDragging().finally(() => {
      window.setTimeout(() => {
        void setFlyoutInteracting(false).catch(() => undefined);
      }, 250);
    });
  };

  return (
    <header
      className="tray-panel__header"
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        const target = event.target as HTMLElement | null;
        if (target?.closest("button")) return;
        event.preventDefault();
        beginDrag();
      }}
    >
      <div className="tray-panel__identity">
        <span className="tray-panel__avatar" aria-hidden="true">
          <AccountAvatar identity={profile} size={36} decorative />
        </span>
        <div className="tray-panel__title-group">
          <p className="tray-panel__identity-name">{identity}</p>
          <h1>{lastUpdatedText}</h1>
          {showAccountStatus ? (
            <p className="tray-panel__identity-status">{secondary}</p>
          ) : null}
        </div>
      </div>
      <div className="tray-panel__header-actions">
        <span className="tray-panel__version">v{version}</span>
        <button
          type="button"
          className="tray-panel__close tray-panel__pin"
          data-pinned={pinned ? "true" : "false"}
          aria-pressed={pinned}
          aria-label={pinned ? unpinLabel : pinLabel}
          title={pinned ? unpinLabel : pinLabel}
          onClick={() => void onTogglePin()}
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            fill={pinned ? "currentColor" : "none"}
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 17v5" />
            <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z" />
          </svg>
        </button>
      </div>
    </header>
  );
}
