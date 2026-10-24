import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { ApiError } from "@/api/errors";
import { scoreJob } from "@/api/jobs";
import type { ScoringConfig, ScoringResponse } from "@/api/types";

import { queryKeys } from "./queryKeys";

/** Score a job; on success its summary and store list are refreshed. */
export function useScoreJob(jobId: number) {
  const queryClient = useQueryClient();
  return useMutation<ScoringResponse, ApiError, ScoringConfig>({
    mutationFn: (config) => scoreJob(jobId, config),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.jobSummary(jobId),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.jobStoresAll(jobId),
        }),
      ]),
  });
}
