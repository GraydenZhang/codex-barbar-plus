import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { trayCopy } from "./copy";
import QuotaCard from "./QuotaCard";

vi.mock("../../hooks/useFormattedResetTime", () => ({
  useFormattedResetTime: () => "2 小时后重置",
}));

const quota = {
  limitId: "five-hour",
  label: "5-hour",
  usedPercent: 30,
  remainingPercent: 70,
  windowDurationMinutes: 300,
  resetsAt: "2026-09-09T15:00:00Z",
  reachedType: null,
};

describe("QuotaCard Plus value order", () => {
  it("prefixes the percentage with remaining in text and accessibility copy", () => {
    render(
      <QuotaCard
        window={quota}
        displayMode="remaining"
        copy={trayCopy("zh-CN")}
        locale="zh-CN"
        timeZone="Asia/Shanghai"
      />,
    );
    expect(screen.getByText("剩余 70%" )).toBeInTheDocument();
    expect(screen.queryByText("70% 剩余")).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAccessibleName(/剩余 70%/);
  });

  it("keeps the upstream used-mode order", () => {
    render(
      <QuotaCard
        window={quota}
        displayMode="used"
        copy={trayCopy("zh-CN")}
        locale="zh-CN"
        timeZone="Asia/Shanghai"
      />,
    );
    expect(screen.getByText("30% 已使用")).toBeInTheDocument();
  });
});
