import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/errors";

/** Retry only what retrying can fix: no response, or a server error. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  const status = error instanceof ApiError ? error.status : null;
  return status === null || status >= 500;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}

// Every failure reaching TanStack Query is an ApiError (the axios client's
// interceptor guarantees it), so type query and mutation errors as such.
declare module "@tanstack/react-query" {
  interface Register {
    defaultError: ApiError;
  }
}
