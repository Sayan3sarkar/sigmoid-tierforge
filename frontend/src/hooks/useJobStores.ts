import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { listJobStores } from "@/api/jobs";
import type { JobStoreFilters, PageParams } from "@/api/types";

import { POLL_INTERVAL_MS, queryKeys } from "./queryKeys";

interface Options {
  /** Refresh while the job runs, so rows change state live. */
  poll: boolean;
}

/** One page of a job's stores; the previous page stays visible while the next loads. */
export function useJobStores(
  jobId: number,
  filters: JobStoreFilters,
  page: PageParams,
  { poll }: Options,
) {
  return useQuery({
    queryKey: queryKeys.jobStores(jobId, filters, page),
    queryFn: () => listJobStores(jobId, filters, page),
    placeholderData: keepPreviousData,
    refetchInterval: poll ? POLL_INTERVAL_MS : false,
  });
}
