import type { UseStatusSurfaceResult } from "../hooks/useStatusSurface";
import type {
  StatusQuotaMetric,
  TrustState,
} from "../lib/statusSurfaceViewModel";
import { quotaBandFor } from "../lib/statusSurfaceViewModel";
import { surfaceAlphaFromTransparency } from "../lib/surfaceTransparency";
import type { UsageWindowDto } from "../types/bridge";

const FIVE_HOUR_MINUTES = 300;
const WEEKLY_MINUTES = 10_080;

export interface TaskbarStatusPresentation {
  plusMode: boolean;
  displayName: string;
  compactIdentity: string | null;
  avatarKind: "default" | "official" | "manual";
  avatarAssetUri: string | null;
  showIcon: boolean;
  showAccount: boolean;
  showWeeklyLabel: boolean;
  showWeeklyPercent: boolean;
  showResetDate: boolean;
  density: "compact" | "standard";
  fiveHourText?: string | null;
  fiveHourResetText?: string | null;
  weeklyText: string | null;
  resetDateText: string | null;
  metrics: readonly StatusQuotaMetric[];
  fiveHour?: StatusQuotaMetric | null;
  weekly?: StatusQuotaMetric | null;
  reset: StatusQuotaMetric | null;
  trustState: TrustState;
  ariaLabel: string;
  surfaceAlpha: string;
}

export function compactTaskbarMetric(metric: StatusQuotaMetric): string {
  return `${metric.shortLabel} ${metric.displayedPercent}%`;
}

function weeklyText(
  metric: StatusQuotaMetric | null,
  showLabel: boolean,
  showPercent: boolean,
): string | null {
  if (!metric) return null;
  const parts: string[] = [];
  if (showLabel) parts.push(metric.shortLabel);
  if (showPercent) parts.push(`${metric.displayedPercent}%`);
  return parts.length > 0 ? parts.join(" ") : null;
}

function resetDateText(metric: StatusQuotaMetric | null): string | null {
  if (!metric?.resetsAt) return null;
  const date = new Date(metric.resetsAt);
  return Number.isNaN(date.valueOf())
    ? null
    : `${date.getMonth() + 1}/${date.getDate()}`;
}

function resetClockText(metric: StatusQuotaMetric | null): string | null {
  if (!metric?.resetsAt) return null;
  const date = new Date(metric.resetsAt);
  if (Number.isNaN(date.valueOf())) return null;
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function shortLabelFor(
  window: UsageWindowDto,
  language: "system" | "zh-CN" | "en-US" | undefined,
): string {
  if (window.windowDurationMinutes === FIVE_HOUR_MINUTES) return "5H";
  if (window.windowDurationMinutes === WEEKLY_MINUTES) {
    return language === "en-US" ? "Wk" : "周";
  }
  const label = window.label?.trim();
  return label ? Array.from(label).slice(0, 6).join("") : "Quota";
}

/**
 * Pick the quota window for a target duration. Prefer the window that the main
 * panel renders (state.primary, then state.secondary) so the taskbar capsule
 * never disagrees with the tray cards. Fall back to additional windows only
 * when neither primary nor secondary matches the requested duration.
 */
function windowForDuration(
  surface: UseStatusSurfaceResult,
  durationMinutes: number,
): UsageWindowDto | null {
  const state = surface.state;
  const ordered: UsageWindowDto[] = [
    state.primary,
    state.secondary,
    ...state.additionalWindows,
  ].filter((window): window is UsageWindowDto => window !== null);
  return (
    ordered.find((window) => window.windowDurationMinutes === durationMinutes) ??
    null
  );
}

function toTaskbarMetric(
  window: UsageWindowDto,
  displayMode: "remaining" | "used",
  trustState: TrustState,
  language: "system" | "zh-CN" | "en-US" | undefined,
): StatusQuotaMetric {
  const remaining = clampPercent(window.remainingPercent);
  const used = clampPercent(window.usedPercent);
  return {
    kind:
      window.windowDurationMinutes === FIVE_HOUR_MINUTES
        ? "fiveHour"
        : window.windowDurationMinutes === WEEKLY_MINUTES
          ? "weekly"
          : "other",
    limitId: window.limitId,
    label: shortLabelFor(window, language),
    shortLabel: shortLabelFor(window, language),
    usedPercent: used,
    remainingPercent: remaining,
    displayedPercent: displayMode === "used" ? used : remaining,
    displayMode,
    resetText: "",
    resetsAt: window.resetsAt,
    band: quotaBandFor(remaining, trustState),
  };
}

export function buildTaskbarStatusPresentation(
  surface: UseStatusSurfaceResult,
): TaskbarStatusPresentation {
  const displayMode = surface.bootstrap?.settings.displayMode ?? "remaining";
  const language = surface.bootstrap?.settings.language;
  const trustState = surface.trustState;

  const fiveHourWindow = windowForDuration(surface, FIVE_HOUR_MINUTES);
  const weeklyWindow = windowForDuration(surface, WEEKLY_MINUTES);

  const fiveHour = fiveHourWindow
    ? toTaskbarMetric(fiveHourWindow, displayMode, trustState, language)
    : null;
  const weekly = weeklyWindow
    ? toTaskbarMetric(weeklyWindow, displayMode, trustState, language)
    : null;

  const prefs = surface.bootstrap?.settings.taskbarPresentation;
  const plusMode = surface.bootstrap?.settings.taskbarShowFiveHour ?? true;
  const showIcon = prefs?.showTaskbarIcon ?? true;
  const showAccount = prefs?.showTaskbarAccount ?? true;
  const showWeeklyLabel = prefs?.showWeeklyLabel ?? true;
  const showWeeklyPercent = prefs?.showWeeklyPercent ?? true;
  const showResetDate = prefs?.showResetDate ?? true;
  const density = prefs?.density ?? "compact";
  const originalMetric = surface.universalMetric;
  const fiveHourValue = plusMode && fiveHour ? compactTaskbarMetric(fiveHour) : null;
  const fiveHourReset = plusMode ? resetClockText(fiveHour) : null;
  const displayedWeekly = plusMode ? weekly : originalMetric;
  const weeklyValue = weeklyText(displayedWeekly, showWeeklyLabel, showWeeklyPercent);
  const weeklyReset = showResetDate ? resetDateText(displayedWeekly) : null;
  const metricsText = [
    fiveHourValue,
    fiveHourReset ? `重置 ${fiveHourReset}` : null,
    weeklyValue,
    plusMode && weeklyReset ? `重置 ${weeklyReset}` : null,
  ]
    .filter(Boolean)
    .join("，") || "无可用额度";
  const trustText =
    surface.trustState === "cached" ? "缓存数据" : surface.refreshStatus;
  const ariaLabel = [
    "打开完整面板",
    showAccount ? surface.displayName : null,
    metricsText,
    plusMode ? null : originalMetric?.resetText,
    trustText,
    surface.updatedText,
  ]
    .filter(Boolean)
    .join("，");

  return {
    plusMode,
    displayName: surface.displayName,
    compactIdentity: showAccount ? surface.compactIdentity : null,
    avatarKind: surface.avatarKind,
    avatarAssetUri: surface.avatarAssetUri,
    showIcon,
    showAccount,
    showWeeklyLabel,
    showWeeklyPercent,
    showResetDate,
    density,
    fiveHourText: fiveHourValue,
    fiveHourResetText: fiveHourReset,
    weeklyText: weeklyValue,
    resetDateText: weeklyReset,
    metrics: plusMode ? surface.metrics : (originalMetric ? [originalMetric] : []),
    fiveHour: plusMode ? fiveHour : null,
    weekly: displayedWeekly,
    reset: displayedWeekly,
    trustState,
    ariaLabel,
    surfaceAlpha: String(
      surfaceAlphaFromTransparency(
        surface.bootstrap?.settings.taskbarTransparencyPercent ?? 20,
      ),
    ),
  };
}
