import { describe, expect, it, vi } from "vitest";
import type { UseStatusSurfaceResult } from "../hooks/useStatusSurface";
import { buildStatusSurfaceViewModel } from "../lib/statusSurfaceViewModel";
import { readyTwoWindowFixture } from "../test/profileUsageFixtures";
import { buildTaskbarStatusPresentation } from "./taskbarStatusPresentation";

function surface(showFiveHour: boolean): UseStatusSurfaceResult {
  const bootstrap = readyTwoWindowFixture();
  bootstrap.settings.taskbarShowFiveHour = showFiveHour;
  bootstrap.profiles[0]!.accountDisplayName = "ProofUser";
  bootstrap.profiles[0]!.presentationName = "ProofUser";
  const profile = bootstrap.profiles[0]!;
  const state = bootstrap.usageByProfile.personal!;
  return {
    ...buildStatusSurfaceViewModel({
      profile,
      state,
      displayMode: bootstrap.settings.displayMode,
      language: bootstrap.settings.language,
      nowMs: Date.parse("2026-08-14T00:00:00Z"),
    }),
    bootstrap,
    profile,
    state,
    isDragging: false,
    closeFailedBySurface: { taskbarStatus: false, floatBall: false },
    setIsDragging: vi.fn(),
    openPanel: vi.fn(async () => {}),
    disableSurface: vi.fn(async () => {}),
    setFloatBallExpanded: vi.fn(async () => {}),
  };
}

describe("taskbar 5H mode", () => {
  it("uses the Plus dual-quota presentation and hides account identity", () => {
    const presentation = buildTaskbarStatusPresentation(surface(true));
    expect(presentation.plusMode).toBe(true);
    expect(presentation.fiveHourText).toMatch(/^5H \d+%$/);
    expect(presentation.weeklyText).toMatch(/^(周|Wk) \d+%$/);
    expect(presentation.showAccount).toBe(false);
    expect(presentation.compactIdentity).toBeNull();
  });

  it("restores the upstream weekly-only presentation and account preference", () => {
    const presentation = buildTaskbarStatusPresentation(surface(false));
    expect(presentation.plusMode).toBe(false);
    expect(presentation.fiveHourText).toBeNull();
    expect(presentation.weeklyText).toMatch(/^(周|Wk) \d+%$/);
    expect(presentation.showAccount).toBe(true);
    expect(presentation.compactIdentity).toBe("ProofU");
  });
});
