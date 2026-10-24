import { useQuery } from "@tanstack/react-query";

import { getJobSummary } from "@/api/jobs";

import { queryKeys } from "./queryKeys";

/**
 * Progress plus the latest scoring. Not polled: the job page refreshes it when
 * the job finishes, and scoring refreshes it on success.
 */
export function useJobSummary(jobId: number) {
  return useQuery({
    queryKey: queryKeys.jobSummary(jobId),
    queryFn: () => getJobSummary(jobId),
  });
}
