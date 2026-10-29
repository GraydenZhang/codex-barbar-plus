import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { render } from "@testing-library/react";
import type { UseStatusSurfaceResult } from "../hooks/useStatusSurface";
import { buildStatusSurfaceViewModel } from "../lib/statusSurfaceViewModel";
import { readyTwoWindowFixture } from "../test/profileUsageFixtures";
import { buildTaskbarStatusPresentation } from "./taskbarStatusPresentation";
import { TaskbarStatusContents } from "./TaskbarStatusContents";

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
  it.each(["visible", "measurement"] as const)("renders the enabled account alongside 5H in %s contents", (mode) => {
    const presentation = buildTaskbarStatusPresentation(surface(true));
    const { container } = render(createElement(TaskbarStatusContents, { mode, presentation }));
    expect(container.querySelector(".taskbar-status__identity")).toHaveTextContent("ProofU");
    expect(container.querySelector(".taskbar-status__metric")).toHaveTextContent(/^5H \d+%$/);
  });

  it("uses the Plus dual-quota presentation and honors enabled account identity", () => {
    const presentation = buildTaskbarStatusPresentation(surface(true));
    expect(presentation.plusMode).toBe(true);
    expect(presentation.fiveHourText).toMatch(/^5H \d+%$/);
    expect(presentation.weeklyText).toMatch(/^(周|Wk) \d+%$/);
    expect(presentation.showAccount).toBe(true);
    expect(presentation.compactIdentity).toBe("ProofU");
    expect(presentation.ariaLabel).toContain("ProofUser");
  });

  it("restores the upstream weekly-only presentation and account preference", () => {
    const presentation = buildTaskbarStatusPresentation(surface(false));
    expect(presentation.plusMode).toBe(false);
    expect(presentation.fiveHourText).toBeNull();
    expect(presentation.weeklyText).toMatch(/^(周|Wk) \d+%$/);
    expect(presentation.showAccount).toBe(true);
    expect(presentation.compactIdentity).toBe("ProofU");
  });

  it.each([true, false])("honors a hidden account with 5H enabled = %s", (showFiveHour) => {
    const model = surface(showFiveHour);
    model.bootstrap!.settings.taskbarPresentation.showTaskbarAccount = false;
    const presentation = buildTaskbarStatusPresentation(model);
    expect(presentation.showAccount).toBe(false);
    expect(presentation.compactIdentity).toBeNull();
    expect(presentation.ariaLabel).not.toContain("ProofUser");
  });

  it("keeps 5H visible when it is the only configured item", () => {
    const model = surface(true);
    model.bootstrap!.settings.taskbarPresentation = {
      ...model.bootstrap!.settings.taskbarPresentation,
      showTaskbarAccount: false,
      showTaskbarIcon: false,
      showWeeklyLabel: false,
      showWeeklyPercent: false,
      showResetDate: false,
    };
    const presentation = buildTaskbarStatusPresentation(model);
    expect(presentation.fiveHourText).toMatch(/^5H \d+%$/);
    expect(presentation.showIcon).toBe(false);
    expect(presentation.compactIdentity).toBeNull();
    expect(presentation.weeklyText).toBeNull();
    expect(presentation.resetDateText).toBeNull();
  });
});
