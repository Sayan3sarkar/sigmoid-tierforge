import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { JobStoreItem } from "@/api/types";
import {
  makeJob,
  makeScoringResponse,
  makeStore,
  makeSummary,
  SCORING_CONFIG,
} from "@/test/fixtures";
import { renderRoute } from "@/test/render";
import { apiUrl, server } from "@/test/server";

const STORES: JobStoreItem[] = [
  makeStore(),
  makeStore({
    task_id: 104,
    store_id: "ST000004",
    store_name: "Corner Grocery #4",
    status: "failed",
    attempt_count: 5,
    last_error: "upstream error (500)",
    estimated_monthly_footfall: null,
    estimated_monthly_revenue: null,
    store_size_sqft: null,
    score: null,
    tier: null,
  }),
  makeStore({
    task_id: 106,
    store_id: "ST000006",
    store_name: "Daily Needs #6",
    status: "retrying",
    attempt_count: 2,
    last_error: "timed out after 10s",
    estimated_monthly_footfall: null,
    estimated_monthly_revenue: null,
    store_size_sqft: null,
    score: null,
    tier: null,
    finished_at: null,
  }),
];

/** Mock the API for job 7; returns the query params of every store-list call. */
function mockJob({ job = makeJob(), summary = makeSummary() } = {}) {
  const storeQueries: URLSearchParams[] = [];
  server.use(
    http.get(apiUrl("/jobs/7"), () => HttpResponse.json(job)),
    http.get(apiUrl("/jobs/7/summary"), () => HttpResponse.json(summary)),
    http.get(apiUrl("/jobs/7/stores"), ({ request }) => {
      const query = new URL(request.url).searchParams;
      storeQueries.push(query);
      const status = query.get("status");
      const items = status
        ? STORES.filter((store) => store.status === status)
        : STORES;
      return HttpResponse.json({ items, total_count: items.length });
    }),
  );
  return storeQueries;
}

describe("JobPage", () => {
  it("shows the job’s progress and its stores", async () => {
    mockJob();
    renderRoute("/jobs/7");

    expect(
      await screen.findByRole("heading", { name: "Job #7" }),
    ).toBeInTheDocument();
    expect(screen.getByText("4 of 4 stores finished")).toBeInTheDocument();
    expect(await screen.findByText("Fresh Supermarket #1")).toBeInTheDocument();
    expect(screen.getByText("4,00,000.00")).toBeInTheDocument();
    expect(screen.getByText("upstream error (500)")).toBeInTheDocument();
  });

  it("filters stores through the URL and the API", async () => {
    const storeQueries = mockJob();
    const { router } = renderRoute("/jobs/7");
    await screen.findByText("Fresh Supermarket #1");

    await userEvent.click(
      within(
        screen.getByRole("radiogroup", { name: "Filter by status" }),
      ).getByText("Failed"),
    );

    await waitFor(() =>
      expect(
        screen.queryByText("Fresh Supermarket #1"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Corner Grocery #4")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?status=failed");
    expect(storeQueries.at(-1)?.get("status")).toBe("failed");
  });

  it("shows stores waiting for a retry, with their attempts", async () => {
    const storeQueries = mockJob({
      job: makeJob({
        status: "running",
        finished_at: null,
        tasks: {
          pending: 0,
          in_progress: 1,
          retrying: 2,
          succeeded: 1,
          failed: 0,
        },
      }),
    });
    const { router } = renderRoute("/jobs/7");
    expect(
      await screen.findByText("Retrying", { selector: "p" }),
    ).toBeInTheDocument();
    expect(screen.getByText("1 of 4 stores finished")).toBeInTheDocument();

    await userEvent.click(
      within(
        screen.getByRole("radiogroup", { name: "Filter by status" }),
      ).getByText("Retrying"),
    );

    await waitFor(() =>
      expect(
        screen.queryByText("Fresh Supermarket #1"),
      ).not.toBeInTheDocument(),
    );
    const row = screen.getByText("Daily Needs #6").closest("tr")!;
    expect(within(row).getByText("Retrying")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(within(row).getByText("timed out after 10s")).toBeInTheDocument();
    expect(router.state.location.search).toBe("?status=retrying");
    expect(storeQueries.at(-1)?.get("status")).toBe("retrying");
  });

  it("scores a finished job and shows the tier breakdown", async () => {
    let summary = makeSummary();
    let scoringBody: unknown;
    mockJob();
    server.use(
      http.get(apiUrl("/jobs/7/summary"), () => HttpResponse.json(summary)),
      http.post(apiUrl("/jobs/7/scoring"), async ({ request }) => {
        scoringBody = await request.json();
        summary = makeSummary({
          scoring: {
            scored_at: "2026-10-23T18:46:09Z",
            config: SCORING_CONFIG,
            tiers: { large: 1, medium: 1, small: 1 },
          },
        });
        return HttpResponse.json(makeScoringResponse());
      }),
    );
    renderRoute("/jobs/7");
    expect(await screen.findByText(/Not scored yet/)).toBeInTheDocument();

    await userEvent.click(
      await screen.findByRole("button", { name: "Score stores" }),
    );

    expect(await screen.findByLabelText("large stores")).toHaveTextContent("1");
    expect(scoringBody).toEqual(SCORING_CONFIG);
    expect(await screen.findByText("3 stores scored.")).toBeInTheDocument();
  });

  it("doesn’t offer scoring while enrichment runs", async () => {
    mockJob({
      job: makeJob({
        status: "running",
        finished_at: null,
        tasks: {
          pending: 2,
          in_progress: 1,
          retrying: 0,
          succeeded: 1,
          failed: 0,
        },
      }),
    });
    renderRoute("/jobs/7");

    expect(
      await screen.findByText(
        "Scoring is available once enrichment has finished.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Score stores" }),
    ).not.toBeInTheDocument();
  });

  it('shows "Job not found" for an unknown job', async () => {
    server.use(
      http.get(apiUrl("/jobs/7"), () =>
        HttpResponse.json(
          { detail: "Job 7 not found.", errors: [] },
          { status: 404 },
        ),
      ),
      http.get(apiUrl("/jobs/7/summary"), () =>
        HttpResponse.json(
          { detail: "Job 7 not found.", errors: [] },
          { status: 404 },
        ),
      ),
      http.get(apiUrl("/jobs/7/stores"), () =>
        HttpResponse.json(
          { detail: "Job 7 not found.", errors: [] },
          { status: 404 },
        ),
      ),
    );
    renderRoute("/jobs/7");

    expect(
      await screen.findByRole("heading", { name: "Job not found" }),
    ).toBeInTheDocument();
  });
});
