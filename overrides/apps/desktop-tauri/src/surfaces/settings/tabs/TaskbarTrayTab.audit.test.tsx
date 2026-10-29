import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { defaultAppSettings } from "../../../hooks/useSettings";
import type { AppSettingsDto, SettingsPatchDto } from "../../../types/bridge";
import { settingsCopy } from "../settingsCopy";
import TaskbarTrayTab from "./TaskbarTrayTab";

const copy = settingsCopy("en-US");
const fiveHourOnly: AppSettingsDto = {
  ...defaultAppSettings,
  taskbarStatusEnabled: true,
  taskbarShowFiveHour: true,
  taskbarPresentation: {
    ...defaultAppSettings.taskbarPresentation,
    showTaskbarIcon: false,
    showTaskbarAccount: false,
    showWeeklyLabel: false,
    showWeeklyPercent: false,
    showResetDate: false,
  },
};

describe("taskbar visible item audit regressions", () => {
  it("counts 5H and prevents hiding only the last enabled item", async () => {
    let saved = fiveHourOnly;
    const update = vi.fn(async (patch: SettingsPatchDto) => {
      saved = { ...saved, ...patch, taskbarPresentation: { ...saved.taskbarPresentation, ...patch.taskbarPresentation } } as AppSettingsDto;
      return saved;
    });
    render(<TaskbarTrayTab settings={saved} update={update} setSurfaceEnabled={vi.fn().mockResolvedValue(saved)} />);
    const fiveHour = screen.getByRole("checkbox", { name: copy.taskbarPresentation.showFiveHour });
    const account = screen.getByRole("checkbox", { name: copy.taskbarPresentation.showAccount });
    expect(fiveHour).toBeChecked();
    expect(fiveHour).toBeDisabled();
    expect(account).toBeEnabled();

    fireEvent.click(account);
    await waitFor(() => expect(fiveHour).toBeEnabled());
    expect(account).toBeChecked();
    fireEvent.click(fiveHour);
    await waitFor(() => expect(fiveHour).not.toBeChecked());
    expect(update).toHaveBeenLastCalledWith({ taskbarShowFiveHour: false });
    expect(account).toBeDisabled();
  });

  it("allows enabling a taskbar whose only configured item is 5H", async () => {
    const setSurfaceEnabled = vi.fn().mockResolvedValue(fiveHourOnly);
    render(<TaskbarTrayTab settings={{ ...fiveHourOnly, taskbarStatusEnabled: false }} update={vi.fn().mockResolvedValue(fiveHourOnly)} setSurfaceEnabled={setSurfaceEnabled} />);
    const enabled = screen.getByRole("checkbox", { name: copy.taskbarPresentation.taskbarEnabled });
    expect(enabled).toBeEnabled();
    fireEvent.click(enabled);
    await waitFor(() => expect(setSurfaceEnabled).toHaveBeenCalledExactlyOnceWith("taskbarStatus", true));
  });

  it("blocks enabling an empty taskbar until an item is selected", () => {
    render(<TaskbarTrayTab settings={{ ...fiveHourOnly, taskbarStatusEnabled: false, taskbarShowFiveHour: false }} update={vi.fn().mockResolvedValue(fiveHourOnly)} setSurfaceEnabled={vi.fn().mockResolvedValue(fiveHourOnly)} />);
    expect(screen.getByRole("checkbox", { name: copy.taskbarPresentation.taskbarEnabled })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: copy.taskbarPresentation.showFiveHour })).toBeEnabled();
  });

  it("restores the 5H switch and shows an inline error when saving fails", async () => {
    const settings = { ...fiveHourOnly, taskbarPresentation: { ...fiveHourOnly.taskbarPresentation, showTaskbarAccount: true } };
    const update = vi.fn().mockRejectedValue("SETTINGS_SAVE_FAILED");
    render(<TaskbarTrayTab settings={settings} update={update} setSurfaceEnabled={vi.fn().mockResolvedValue(settings)} />);
    const fiveHour = screen.getByRole("checkbox", { name: copy.taskbarPresentation.showFiveHour });
    fireEvent.click(fiveHour);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.taskbarPresentation.preferencesSaveFailed);
    expect(fiveHour).toBeChecked();
    expect(fiveHour).toBeEnabled();
  });
});
