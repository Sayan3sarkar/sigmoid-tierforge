import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "@/queryClient";
import { makeJob, makeSummary } from "@/test/fixtures";
import { apiUrl, server } from "@/test/server";

import { POLL_INTERVAL_MS, queryKeys } from "./queryKeys";
import { jobRefetchInterval, useJob } from "./useJob";

function wrapperWith(client = createQueryClient()) {
  client.setDefaultOptions({ queries: { retry: false } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

describe("jobRefetchInterval", () => {
  it("polls while the job is pending or running", () => {
    expect(jobRefetchInterval(makeJob({ status: "pending" }))).toBe(
      POLL_INTERVAL_MS,
    );
    expect(jobRefetchInterval(makeJob({ status: "running" }))).toBe(
      POLL_INTERVAL_MS,
    );
  });

  it("stops once the job has finished or failed", () => {
    expect(jobRefetchInterval(makeJob({ status: "completed" }))).toBe(false);
    expect(
      jobRefetchInterval(makeJob({ status: "completed_with_failures" })),
    ).toBe(false);
    expect(jobRefetchInterval(makeJob({ status: "failed" }))).toBe(false);
    expect(jobRefetchInterval(undefined)).toBe(false);
  });
});

describe("useJob", () => {
  it("loads the job from the API", async () => {
    server.use(http.get(apiUrl("/jobs/7"), () => HttpResponse.json(makeJob())));
    const { wrapper } = wrapperWith();

    const { result } = renderHook(() => useJob(7), { wrapper });

    await waitFor(() => expect(result.current.data).toEqual(makeJob()));
  });

  it("refreshes the summary once the job finishes", async () => {
    let status: "running" | "completed" = "running";
    server.use(
      http.get(apiUrl("/jobs/7"), () => HttpResponse.json(makeJob({ status }))),
      http.get(apiUrl("/jobs/7/summary"), () =>
        HttpResponse.json(makeSummary()),
      ),
    );
    const { client, wrapper } = wrapperWith();
    // Something (the job page) is showing the summary.
    await client.fetchQuery({
      queryKey: queryKeys.jobSummary(7),
      queryFn: () => makeSummary({ status: "running" }),
    });

    const { result } = renderHook(() => useJob(7), { wrapper });
    await waitFor(() => expect(result.current.data?.status).toBe("running"));
    expect(client.getQueryState(queryKeys.jobSummary(7))?.isInvalidated).toBe(
      false,
    );

    status = "completed";
    await result.current.refetch();

    await waitFor(() =>
      expect(client.getQueryState(queryKeys.jobSummary(7))?.isInvalidated).toBe(
        true,
      ),
    );
  });
});
