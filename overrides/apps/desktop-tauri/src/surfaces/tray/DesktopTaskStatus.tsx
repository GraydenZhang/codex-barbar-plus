import { useEffect, useMemo, useState } from "react";
import type {
  DesktopTaskDto,
  DesktopTaskSnapshotDto,
} from "../../hooks/useDesktopTasks";

function formatDuration(task: DesktopTaskDto, nowMs: number): string {
  const explicit = task.durationSeconds;
  let totalSeconds = explicit ?? 0;
  if (task.status === "working") {
    const started = Date.parse(task.startedAt);
    if (Number.isFinite(started)) {
      totalSeconds = Math.max(0, Math.floor((nowMs - started) / 1000));
    }
  }
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m${String(seconds).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h${String(minutes % 60).padStart(2, "0")}m`;
}

function statusText(status: DesktopTaskDto["status"], zh: boolean): string {
  switch (status) {
    case "working":
      return zh ? "工作中" : "Working";
    case "completed":
      return zh ? "完成待查看" : "Ready for review";
    case "error":
      return zh ? "需要检查" : "Needs attention";
  }
}

export default function DesktopTaskStatus({
  snapshot,
  language,
}: {
  snapshot: DesktopTaskSnapshotDto;
  language: "system" | "zh-CN" | "en-US";
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const zh = language !== "en-US";

  useEffect(() => {
    if (!snapshot.tasks.some((task) => task.status === "working")) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [snapshot.tasks]);

  const tasks = useMemo(() => snapshot.tasks.slice(0, 5), [snapshot.tasks]);
  if (tasks.length === 0) return null;

  return (
    <section
      className="tray-region desktop-task-status"
      role="region"
      aria-label={zh ? "Codex Desktop 任务" : "Codex Desktop tasks"}
    >
      <h2>{zh ? "Codex Desktop" : "Codex Desktop"}</h2>
      <div className="desktop-task-status__list">
        {tasks.map((task) => (
          <div
            key={task.id}
            className="desktop-task-status__row"
            data-status={task.status}
          >
            <span className="desktop-task-status__dot" aria-hidden="true" />
            <span className="desktop-task-status__title" title={task.title}>
              {task.title}
            </span>
            <span className="desktop-task-status__state">
              {statusText(task.status, zh)}
            </span>
            <span className="desktop-task-status__duration">
              {formatDuration(task, nowMs)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
