import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { getJob } from "@/api/jobs";
import type { Job } from "@/api/types";
import { JobStatusRules } from "@/utils/status";

import { POLL_INTERVAL_MS, queryKeys } from "./queryKeys";

/** Poll while enrichment runs; stop once the job has finished. */
export function jobRefetchInterval(job: Job | undefined): number | false {
  return JobStatusRules.isActive(job?.status) ? POLL_INTERVAL_MS : false;
}

/**
 * The job and its progress, refreshed every few seconds while it runs. When it
 * finishes, its summary and store list are refreshed once more, so they show
 * the final state.
 */
export function useJob(jobId: number) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.job(jobId),
    queryFn: () => getJob(jobId),
    refetchInterval: (current) => jobRefetchInterval(current.state.data),
  });

  const status = query.data?.status;
  const previousStatus = useRef(status);
  useEffect(() => {
    const finished =
      JobStatusRules.isActive(previousStatus.current) &&
      !JobStatusRules.isActive(status);
    if (finished && status !== undefined) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.jobSummary(jobId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.jobStoresAll(jobId),
      });
    }
    previousStatus.current = status;
  }, [jobId, status, queryClient]);

  return query;
}
