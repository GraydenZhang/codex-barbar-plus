import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { defaultAppSettings } from "../../../hooks/useSettings";
import type { AppSettingsDto, NotificationSound, SettingsPatchDto } from "../../../types/bridge";
import { settingsCopy } from "../settingsCopy";
import NotificationsTab from "./NotificationsTab";

const copy = settingsCopy("en-US");
const getCapability = async () => ({ status: "available" as const, canOpenSettings: true });

function setup(update = vi.fn().mockResolvedValue(undefined), previewSound = vi.fn().mockResolvedValue(undefined)) {
  function Harness() {
    const [settings, setSettings] = useState<AppSettingsDto>({
      ...defaultAppSettings,
      notifications: { ...defaultAppSettings.notifications, enabled: true, warningRemainingPercent: 66, dangerRemainingPercent: 33, resetSound: "default" },
    });
    const save = async (patch: SettingsPatchDto) => {
      await update(patch);
      setSettings((previous) => ({
        ...previous,
        notifications: { ...previous.notifications, ...patch.notifications },
      }));
    };
    return <NotificationsTab settings={settings} update={save} copy={copy} getCapability={getCapability} previewSound={previewSound} />;
  }
  render(<Harness />);
  return { update, previewSound };
}

describe("notification input and preview audit regressions", () => {
  it("allows typing 50 from 66 without saving the invalid intermediate 5", async () => {
    const { update } = setup();
    const warning = screen.getByRole("spinbutton", { name: /warning remaining/i });
    act(() => warning.focus());
    fireEvent.change(warning, { target: { value: "" } });
    fireEvent.change(warning, { target: { value: "5" } });
    expect(update).not.toHaveBeenCalled();
    expect(warning).toHaveValue(5);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.change(warning, { target: { value: "50" } });
    fireEvent.blur(warning);
    await waitFor(() => expect(update).toHaveBeenCalledExactlyOnceWith({ notifications: { warningRemainingPercent: 50 } }));
    expect(warning).toHaveValue(50);
  });

  it("commits a completed number on Enter exactly once", async () => {
    const { update } = setup();
    const danger = screen.getByRole("spinbutton", { name: /danger remaining/i });
    act(() => danger.focus());
    fireEvent.change(danger, { target: { value: "25" } });
    fireEvent.keyDown(danger, { key: "Enter" });
    await waitFor(() => expect(update).toHaveBeenCalledExactlyOnceWith({ notifications: { dangerRemainingPercent: 25 } }));
    expect(danger).toHaveValue(25);
  });

  it.each(["", "20", "101", "50.5"])("rejects invalid warning draft %s on commit and restores saved value", async (value) => {
    const { update } = setup();
    const warning = screen.getByRole("spinbutton", { name: /warning remaining/i });
    fireEvent.change(warning, { target: { value } });
    fireEvent.blur(warning);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notifications.thresholdInvalid);
    expect(update).not.toHaveBeenCalled();
    expect(warning).toHaveValue(66);
  });

  it("restores the saved threshold when storage rejects a valid draft", async () => {
    const { update } = setup(vi.fn().mockRejectedValue("SETTINGS_SAVE_FAILED"));
    const warning = screen.getByRole("spinbutton", { name: /warning remaining/i });
    fireEvent.change(warning, { target: { value: "50" } });
    fireEvent.blur(warning);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notifications.saveFailed);
    expect(update).toHaveBeenCalledTimes(1);
    expect(warning).toHaveValue(66);
  });

  it("Escape discards a threshold draft without writing settings", async () => {
    const { update } = setup();
    const warning = screen.getByRole("spinbutton", { name: /warning remaining/i });
    act(() => warning.focus());
    fireEvent.change(warning, { target: { value: "50" } });
    fireEvent.keyDown(warning, { key: "Escape" });
    fireEvent.blur(warning);
    await act(async () => { await Promise.resolve(); });
    expect(warning).toHaveValue(66);
    expect(update).not.toHaveBeenCalled();
  });

  it("reports preview failure after a successful save and keeps the selected sound", async () => {
    const { update, previewSound } = setup(undefined, vi.fn().mockRejectedValue("PLAYBACK_FAILED"));
    const sound = screen.getByRole("combobox", { name: copy.notifications.resetSound });
    await waitFor(() => expect(sound).toBeEnabled());
    fireEvent.change(sound, { target: { value: "reminder" satisfies NotificationSound } });
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notifications.soundPreviewFailed);
    expect(screen.getByRole("alert")).not.toHaveTextContent(copy.notifications.saveFailed);
    expect(sound).toHaveValue("reminder");
    expect(update).toHaveBeenCalledExactlyOnceWith({ notifications: { resetSound: "reminder" } });
    expect(previewSound).toHaveBeenCalledExactlyOnceWith("reminder");
  });

  it("does not preview or change the saved sound if saving fails", async () => {
    const { previewSound } = setup(vi.fn().mockRejectedValue("SETTINGS_SAVE_FAILED"));
    const sound = screen.getByRole("combobox", { name: copy.notifications.resetSound });
    await waitFor(() => expect(sound).toBeEnabled());
    fireEvent.change(sound, { target: { value: "mail" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notifications.saveFailed);
    expect(sound).toHaveValue("default");
    expect(previewSound).not.toHaveBeenCalled();
  });
});
