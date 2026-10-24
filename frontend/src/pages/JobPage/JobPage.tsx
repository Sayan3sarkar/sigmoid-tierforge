import { Anchor, Card, Group, Stack, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Link, useParams, useSearchParams } from "react-router";

import type { JobStoreFilters, ScoringConfig } from "@/api/types";
import { ApiErrorAlert } from "@/components/ApiErrorAlert";
import { JobProgress } from "@/components/JobProgress";
import { ScoringForm } from "@/components/ScoringForm";
import { StatusBadge } from "@/components/StatusBadge";
import { StoreFilters } from "@/components/StoreFilters";
import { StoreTable } from "@/components/StoreTable";
import { TablePagination } from "@/components/TablePagination";
import { TierSummary } from "@/components/TierSummary";
import { useJob } from "@/hooks/useJob";
import { useJobStores } from "@/hooks/useJobStores";
import { useJobSummary } from "@/hooks/useJobSummary";
import { useScoreJob } from "@/hooks/useScoreJob";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { Format } from "@/utils/format";
import { DEFAULT_SCORING_CONFIG } from "@/utils/scoring";
import { SearchParams } from "@/utils/searchParams";
import { JobStatusRules } from "@/utils/status";

const STORES_PAGE_SIZE = 25;

/** One job: progress, scoring, tier breakdown and its stores. */
export function JobPage() {
  const jobId = Number(useParams().jobId);
  if (!Number.isInteger(jobId) || jobId < 1) return <NotFoundPage />;
  return <JobDetails jobId={jobId} />;
}

function JobDetails({ jobId }: { jobId: number }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = SearchParams.readStoreFilters(searchParams);
  const page = SearchParams.readPage(searchParams);

  const job = useJob(jobId);
  const summary = useJobSummary(jobId);
  const isRunning = JobStatusRules.isActive(job.data?.status);
  const stores = useJobStores(
    jobId,
    filters,
    { page, pageSize: STORES_PAGE_SIZE },
    { poll: isRunning },
  );
  const scoring = useScoreJob(jobId);

  if (job.error?.status === 404) {
    return (
      <Stack>
        <Title order={2}>Job not found</Title>
        <Text>
          There's no job #{jobId}.{" "}
          <Anchor component={Link} to="/jobs">
            See all jobs
          </Anchor>
        </Text>
      </Stack>
    );
  }
  if (job.error)
    return <ApiErrorAlert error={job.error} title="Couldn't load the job" />;
  if (!job.data) return <Text c="dimmed">Loading job…</Text>;

  const changeFilters = (next: JobStoreFilters) =>
    setSearchParams(SearchParams.forStoreList(next, 1));
  const changePage = (next: number) =>
    setSearchParams(SearchParams.forStoreList(filters, next));
  const submitScoring = async (config: ScoringConfig) => {
    const result = await scoring.mutateAsync(config);
    notifications.show({
      color: "teal",
      title: "Stores scored",
      message: `${Format.integer(result.scored_count)} stores scored.`,
    });
  };

  return (
    <Stack gap="xl">
      <Group gap="sm">
        <Title order={2}>Job #{jobId}</Title>
        <StatusBadge status={job.data.status} />
      </Group>

      <JobProgress job={job.data} />

      <Card withBorder padding="lg">
        <Stack gap="md">
          <Title order={4}>Scoring</Title>
          {JobStatusRules.isScorable(job.data.status) ? (
            summary.data && (
              <ScoringForm
                // Remount when the saved settings change, so the form shows them.
                key={summary.data.scoring?.scored_at ?? "unscored"}
                initialConfig={
                  summary.data.scoring?.config ?? DEFAULT_SCORING_CONFIG
                }
                onSubmit={submitScoring}
                submitting={scoring.isPending}
                serverError={scoring.error}
              />
            )
          ) : (
            <Text c="dimmed" size="sm">
              {job.data.status === "failed"
                ? "This job failed, so it can’t be scored."
                : "Scoring is available once enrichment has finished."}
            </Text>
          )}
        </Stack>
      </Card>

      <Card withBorder padding="lg">
        <Stack gap="md">
          <Title order={4}>Tier breakdown</Title>
          {summary.error ? (
            <ApiErrorAlert
              error={summary.error}
              title="Couldn't load the summary"
            />
          ) : (
            <TierSummary scoring={summary.data?.scoring ?? null} />
          )}
        </Stack>
      </Card>

      <Stack gap="md">
        <Title order={4}>Stores</Title>
        <StoreFilters filters={filters} onChange={changeFilters} />
        {stores.error && (
          <ApiErrorAlert error={stores.error} title="Couldn't load stores" />
        )}
        <StoreTable
          items={stores.data?.items ?? []}
          loading={stores.isPending}
        />
        {stores.data && (
          <TablePagination
            page={page}
            pageSize={STORES_PAGE_SIZE}
            totalCount={stores.data.total_count}
            onChange={changePage}
          />
        )}
      </Stack>
    </Stack>
  );
}
