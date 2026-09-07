import type { UseStatusSurfaceResult } from "../hooks/useStatusSurface";
import type {
  StatusQuotaMetric,
  TrustState,
} from "../lib/statusSurfaceViewModel";
import { surfaceAlphaFromTransparency } from "../lib/surfaceTransparency";

export interface TaskbarStatusPresentation {
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

export function buildTaskbarStatusPresentation(
  surface: UseStatusSurfaceResult,
): TaskbarStatusPresentation {
  const metrics = surface.metrics;
  const fiveHour =
    surface.primaryMetric ??
    metrics.find((metric) => metric.kind === "fiveHour") ??
    null;
  const weekly =
    surface.secondaryMetric ??
    surface.universalMetric ??
    metrics.find((metric) => metric.kind === "weekly") ??
    null;
  const prefs = surface.bootstrap?.settings.taskbarPresentation;
  const showIcon = prefs?.showTaskbarIcon ?? true;
  // codex-barbar-plus intentionally keeps account identity out of the resident
  // taskbar capsule. The full tray panel still shows the selected account.
  const showAccount = false;
  const showWeeklyLabel = prefs?.showWeeklyLabel ?? true;
  const showWeeklyPercent = prefs?.showWeeklyPercent ?? true;
  const showResetDate = prefs?.showResetDate ?? true;
  const density = prefs?.density ?? "compact";
  const fiveHourValue = fiveHour ? compactTaskbarMetric(fiveHour) : null;
  const fiveHourReset = resetClockText(fiveHour);
  const weeklyValue = weeklyText(weekly, showWeeklyLabel, showWeeklyPercent);
  const weeklyReset = showResetDate ? resetDateText(weekly) : null;
  const metricsText = [
    fiveHourValue,
    fiveHourReset ? `重置 ${fiveHourReset}` : null,
    weeklyValue,
    weeklyReset ? `重置 ${weeklyReset}` : null,
  ]
    .filter(Boolean)
    .join("，") || "无可用额度";
  const trustText =
    surface.trustState === "cached" ? "缓存数据" : surface.refreshStatus;
  const ariaLabel = [
    "打开完整面板",
    metricsText,
    trustText,
    surface.updatedText,
  ]
    .filter(Boolean)
    .join("，");

  return {
    displayName: surface.displayName,
    compactIdentity: null,
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
    metrics,
    fiveHour,
    weekly,
    reset: weekly,
    trustState: surface.trustState,
    ariaLabel,
    surfaceAlpha: String(
      surfaceAlphaFromTransparency(
        surface.bootstrap?.settings.taskbarTransparencyPercent ?? 20,
      ),
    ),
  };
}
