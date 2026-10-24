import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { ApiError } from "@/api/errors";
import type { UploadResponse } from "@/api/types";
import { uploadStores } from "@/api/uploads";

/** Upload a CSV; on success the job list is refreshed. */
export function useUploadStores() {
  const queryClient = useQueryClient();
  return useMutation<UploadResponse, ApiError, File>({
    mutationFn: uploadStores,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  });
}
