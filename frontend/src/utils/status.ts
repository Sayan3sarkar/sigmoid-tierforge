import type { JobStatus, TaskCounts, TaskStatus, Tier } from "@/api/types";

const ACTIVE_JOB_STATUSES: readonly JobStatus[] = ["pending", "running"];
const SCORABLE_JOB_STATUSES: readonly JobStatus[] = [
  "completed",
  "completed_with_failures",
];

export const TASK_STATUSES: readonly TaskStatus[] = [
  "pending",
  "in_progress",
  "retrying",
  "succeeded",
  "failed",
];
export const TIERS: readonly Tier[] = ["large", "medium", "small"];

export class JobStatusRules {
  /** Enrichment is still going: keep polling. */
  static isActive(status: JobStatus | undefined): boolean {
    return status !== undefined && ACTIVE_JOB_STATUSES.includes(status);
  }

  /** Enrichment has finished, so the job can be scored. */
  static isScorable(status: JobStatus | undefined): boolean {
    return status !== undefined && SCORABLE_JOB_STATUSES.includes(status);
  }

  /** Tasks that have finished, successfully or not. */
  static finishedCount(tasks: TaskCounts): number {
    return tasks.succeeded + tasks.failed;
  }
}

/** Mantine colour per job status, task status and tier. */
export const STATUS_COLOURS: Record<JobStatus | TaskStatus, string> = {
  pending: "gray",
  running: "blue",
  in_progress: "blue",
  retrying: "orange",
  succeeded: "teal",
  completed: "teal",
  completed_with_failures: "yellow",
  failed: "red",
};

export const TIER_COLOURS: Record<Tier, string> = {
  large: "violet",
  medium: "cyan",
  small: "gray",
};
