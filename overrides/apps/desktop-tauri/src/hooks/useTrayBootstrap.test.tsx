import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { invokeMock } from "../test/setup";
import { bootstrapWithTwoProfiles } from "../test/profileUsageFixtures";
import { useTrayBootstrap } from "./useTrayBootstrap";
import type { AppSettingsDto, BootstrapDto } from "../types/bridge";

const harness = vi.hoisted(() => ({
  handler: null as ((event: { payload: AppSettingsDto }) => void) | null,
  unlisten: vi.fn(),
}));
vi.mock("@tauri-apps/api/event", () => ({
  listen: async (_event: string, handler: (event: { payload: AppSettingsDto }) => void) => {
    harness.handler = handler;
    return harness.unlisten;
  },
}));

describe("useTrayBootstrap", () => {
  beforeEach(() => {
    harness.handler = null;
    harness.unlisten.mockReset();
    invokeMock.mockReset();
  });

  it("retains settings delivered while the initial snapshot is pending and unsubscribes", async () => {
    const initial = bootstrapWithTwoProfiles();
    let resolve!: (snapshot: BootstrapDto) => void;
    invokeMock.mockReturnValue(new Promise<BootstrapDto>((done) => { resolve = done; }));
    const { result, unmount } = renderHook(useTrayBootstrap);
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("get_bootstrap_state"));
    const settings: AppSettingsDto = { ...initial.settings, language: "zh-CN", displayMode: "used" };
    act(() => harness.handler?.({ payload: settings }));
    await act(async () => resolve(initial));
    expect(result.current.bootstrap?.settings).toEqual(settings);
    expect(result.current.bootstrap?.usageByProfile).toBe(initial.usageByProfile);
    unmount();
    expect(harness.unlisten).toHaveBeenCalledOnce();
  });

  it("reports a failed snapshot without fabricating dashboard data", async () => {
    invokeMock.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(useTrayBootstrap);
    await waitFor(() => expect(result.current.bootstrapError).toBe(true));
    expect(result.current.bootstrap).toBeNull();
  });
});
