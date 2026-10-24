import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { listJobs } from "@/api/jobs";
import type { PageParams } from "@/api/types";

import { queryKeys } from "./queryKeys";

/** One page of jobs, newest first. */
export function useJobs(page: PageParams) {
  return useQuery({
    queryKey: queryKeys.jobs(page),
    queryFn: () => listJobs(page),
    placeholderData: keepPreviousData,
  });
}
