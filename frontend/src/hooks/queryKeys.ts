import type { JobStoreFilters, PageParams } from "@/api/types";

/**
 * Every TanStack Query key, built in one place. Keys are hierarchical, so
 * invalidating `job(id)` also refreshes that job's summary and stores.
 */
export const queryKeys = {
  jobs: (page: PageParams) => ["jobs", page] as const,
  job: (jobId: number) => ["job", jobId] as const,
  jobSummary: (jobId: number) => ["job", jobId, "summary"] as const,
  jobStoresAll: (jobId: number) => ["job", jobId, "stores"] as const,
  jobStores: (jobId: number, filters: JobStoreFilters, page: PageParams) =>
    ["job", jobId, "stores", filters, page] as const,
};

/** How often a running job's progress and stores are refreshed. */
export const POLL_INTERVAL_MS = 3_000;
