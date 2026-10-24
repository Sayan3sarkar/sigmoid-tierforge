import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "@/queryClient";
import {
  makeScoringResponse,
  makeSummary,
  SCORING_CONFIG,
} from "@/test/fixtures";
import { apiUrl, server } from "@/test/server";

import { queryKeys } from "./queryKeys";
import { useScoreJob } from "./useScoreJob";

describe("useScoreJob", () => {
  it("scores the job, then refreshes its summary and stores", async () => {
    server.use(
      http.post(apiUrl("/jobs/7/scoring"), () =>
        HttpResponse.json(makeScoringResponse()),
      ),
    );
    const client = createQueryClient();
    const page = { page: 1, pageSize: 25 };
    client.setQueryData(queryKeys.jobSummary(7), makeSummary());
    client.setQueryData(queryKeys.jobStores(7, {}, page), {
      items: [],
      total_count: 0,
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useScoreJob(7), { wrapper });
    await act(() => result.current.mutateAsync(SCORING_CONFIG));

    await waitFor(() => {
      expect(client.getQueryState(queryKeys.jobSummary(7))?.isInvalidated).toBe(
        true,
      );
      expect(
        client.getQueryState(queryKeys.jobStores(7, {}, page))?.isInvalidated,
      ).toBe(true);
    });
  });

  it("exposes the API error when scoring is rejected", async () => {
    server.use(
      http.post(apiUrl("/jobs/7/scoring"), () =>
        HttpResponse.json(
          {
            detail:
              "Job 7 is running; it can be scored once enrichment has finished.",
            errors: [],
          },
          { status: 409 },
        ),
      ),
    );
    const client = createQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useScoreJob(7), { wrapper });
    await act(() =>
      result.current.mutateAsync(SCORING_CONFIG).catch(() => undefined),
    );

    await waitFor(() => expect(result.current.error?.status).toBe(409));
  });
});
