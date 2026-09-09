import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { getDesktopTaskSnapshot } from "../lib/tauri";

export type DesktopTaskStatus = "working" | "completed" | "error";

export interface DesktopTaskDto {
  id: string;
  threadId: string;
  title: string;
  status: DesktopTaskStatus;
  startedAt: string;
  finishedAt: string | null;
  durationSeconds: number | null;
}

export interface DesktopTaskSnapshotDto {
  tasks: DesktopTaskDto[];
  updatedAt: string | null;
}

const EMPTY: DesktopTaskSnapshotDto = {
  tasks: [],
  updatedAt: null,
};

function isDesktopTaskSnapshot(value: unknown): value is DesktopTaskSnapshotDto {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as Partial<DesktopTaskSnapshotDto>;
  return Array.isArray(snapshot.tasks) && snapshot.tasks.every((task) =>
    Boolean(task) &&
    typeof task.id === "string" &&
    typeof task.threadId === "string" &&
    typeof task.title === "string" &&
    ["working", "completed", "error"].includes(task.status),
  );
}

export function useDesktopTasks(): DesktopTaskSnapshotDto {
  const [snapshot, setSnapshot] = useState<DesktopTaskSnapshotDto>(EMPTY);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void | Promise<void>) | undefined;

    void getDesktopTaskSnapshot()
      .then((next) => {
        if (active && isDesktopTaskSnapshot(next)) setSnapshot(next);
      })
      .catch(() => {});

    void listen<DesktopTaskSnapshotDto>(
      "desktop-task-state-changed",
      (event) => {
        if (active && isDesktopTaskSnapshot(event.payload)) setSnapshot(event.payload);
      },
    )
      .then((nextUnlisten) => {
        if (active) unlisten = nextUnlisten;
        else void nextUnlisten();
      })
      .catch(() => {});

    return () => {
      active = false;
      void unlisten?.();
    };
  }, []);

  return snapshot;
}
