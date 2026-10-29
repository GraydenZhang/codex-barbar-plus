import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invokeMock } from "../test/setup";
import { bootstrapWithTwoProfiles, profileUsageFixture } from "../test/profileUsageFixtures";
import { events } from "../lib/tauri";
import { resolveLanguage } from "../lib/resolveLanguage";
import type { UsageSpendDto } from "../types/bridge";
import TrayPanel from "./TrayPanel";
import Settings from "./Settings";
import UsageSpendTab, { formatTokenCount } from "./settings/tabs/UsageSpendTab";
import { settingsCopy } from "./settings/settingsCopy";

type Handler = (event: { payload: unknown }) => void;
const eventHarness = vi.hoisted(() => ({
  listeners: new Map<string, Set<Handler>>(),
  emit(name: string, payload: unknown) {
    this.listeners.get(name)?.forEach((handler) => handler({ payload }));
  },
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: async (name: string, handler: Handler) => {
    const handlers = eventHarness.listeners.get(name) ?? new Set<Handler>();
    handlers.add(handler);
    eventHarness.listeners.set(name, handlers);
    return () => { handlers.delete(handler); };
  },
}));

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({ startDragging: async () => {} }),
}));

function mockBootstrap() {
  const bootstrap = bootstrapWithTwoProfiles();
  invokeMock.mockImplementation(async (command: string) => {
    if (command === "get_bootstrap_state") return bootstrap;
    if (command === "get_settings_snapshot") return bootstrap.settings;
    if (command === "get_flyout_pinned") return false;
    if (command === "select_profile") return { profiles: bootstrap.profiles, selectedProfileId: "work" };
    return undefined;
  });
  return bootstrap;
}

describe("UI audit regressions", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    eventHarness.listeners.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("updates open-tray preferences without replacing the selected account or newer usage", async () => {
    const bootstrap = mockBootstrap();
    render(<TrayPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Profile" }));
    fireEvent.click(screen.getByRole("option", { name: /Work/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Profile" })).toHaveTextContent("Work"));
    act(() => eventHarness.emit(events.profileUsageStateChanged, profileUsageFixture("work", 73)));
    expect(screen.getByRole("progressbar", { name: /remaining 73%/ })).toBeInTheDocument();

    act(() => eventHarness.emit(events.settingsChanged, {
      ...bootstrap.settings,
      language: "zh-CN",
      displayMode: "used",
      theme: "dark",
      panel: {
        ...bootstrap.settings.panel,
        density: "standard",
        showResetTime: false,
        actions: { order: ["refresh", "quit", "settings"], hidden: ["settings"] },
      },
    }));

    expect(screen.getByRole("main")).toHaveAttribute("data-density", "standard");
    expect(screen.getByRole("button", { name: "账户配置" })).toHaveTextContent("Work");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "27");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(document.querySelector(".quota-card__reset")).toBeNull();
    expect(within(screen.getByRole("region", { name: "操作" })).getAllByRole("button").map((node) => node.textContent))
      .toEqual(["刷新", "退出"]);
    expect(invokeMock.mock.calls.filter(([command]) => command === "get_bootstrap_state")).toHaveLength(1);
  });

  it("closes the account dropdown on the first Escape and the tray on the next", async () => {
    mockBootstrap();
    render(<TrayPanel />);
    const selector = await screen.findByRole("button", { name: "Profile" });
    fireEvent.click(selector);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(screen.getAllByRole("option")[0], { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(selector).toHaveFocus();
    expect(invokeMock).not.toHaveBeenCalledWith("dismiss_tray_panel");
    fireEvent.keyDown(selector, { key: "Escape" });
    expect(invokeMock).toHaveBeenCalledWith("dismiss_tray_panel");
  });

  it("returns the settings pane to its top for mouse, keyboard, and native tab changes", async () => {
    mockBootstrap();
    render(<Settings />);
    const accounts = await screen.findByRole("button", { name: "Accounts" });
    const pane = document.querySelector<HTMLDivElement>(".settings-panel__pane")!;
    pane.scrollTop = 600;
    fireEvent.click(accounts);
    expect(pane.scrollTop).toBe(0);
    pane.scrollTop = 400;
    fireEvent.keyDown(accounts, { key: "ArrowUp" });
    expect(pane.scrollTop).toBe(0);
    pane.scrollTop = 300;
    act(() => eventHarness.emit("settings-change-tab", "providers"));
    expect(pane.scrollTop).toBe(0);
    expect(accounts).toHaveAttribute("aria-pressed", "true");
  });

  it.each(["zh-CN", "zh-TW"])("formats system-language usage dates and token units consistently for %s", async (systemLanguage) => {
    vi.spyOn(navigator, "language", "get").mockReturnValue(systemLanguage);
    const date = "2026-09-18T06:29:00Z";
    const payload: UsageSpendDto = {
      official: {
        remainingPercent: 66, resetsAt: date, fetchedAt: null, freshness: "fresh",
        resetCredits: { state: "unsupported", availableCount: null, observedAt: null },
      },
      local: {
        attribution: "deviceCombined", range: "last7Days", inputTokens: 0,
        cachedInputTokens: 0, outputTokens: 0, totalTokens: 0, sessionsCount: 0,
        estimatedCost: { amount: null, currency: "USD", provenance: "unpriced", canonicalModel: null, sourceUpdatedAt: null },
        displayCurrency: "USD", pricingStatus: "unpriced", partialEstimate: false,
        unpricedModelCount: 0, unknownModels: [], daily: [], activity: [], models: [],
        state: "empty", malformedRecordsSkipped: 0,
      },
    };
    invokeMock.mockResolvedValue(payload);
    render(<UsageSpendTab language="system" copy={settingsCopy("system")} />);
    const expected = new Intl.DateTimeFormat("zh-CN", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    }).format(new Date(date));
    expect(await screen.findByText((text) => text.includes(expected))).toBeInTheDocument();
    expect(formatTokenCount(12_500, "system")).toBe("1.25万");
    expect(resolveLanguage("system")).toBe("zh-CN");
  });

  it("uses English for system-language tray additions on English Windows", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-GB");
    const bootstrap = mockBootstrap();
    bootstrap.settings.language = "system";
    render(<TrayPanel />);
    await screen.findByRole("button", { name: "Profile" });
    expect(screen.getByRole("button", { name: "Pin" })).toBeInTheDocument();
    expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
    act(() => eventHarness.emit("desktop-task-state-changed", {
      tasks: [{
        id: "review", threadId: "review", title: "Review changes", status: "completed",
        startedAt: "2026-09-12T00:00:00Z", finishedAt: "2026-09-12T00:01:00Z", durationSeconds: 60,
      }],
      updatedAt: "2026-09-12T00:01:00Z",
    }));
    expect(screen.getByText("Ready for review")).toBeInTheDocument();
    expect(resolveLanguage("system")).toBe("en-US");
    expect(resolveLanguage("zh-CN")).toBe("zh-CN");
  });
});
