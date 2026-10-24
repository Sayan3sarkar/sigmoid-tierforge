import {
  Alert,
  Card,
  Group,
  Progress,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";

import type { Job } from "@/api/types";
import { StatusBadge } from "@/components/StatusBadge";
import { Format } from "@/utils/format";
import { JobStatusRules, STATUS_COLOURS } from "@/utils/status";

import classes from "./JobProgress.module.css";

interface Props {
  job: Job;
}

/** A job's status, a progress bar, and its task counts and timings. */
export function JobProgress({ job }: Props) {
  const { tasks, total_tasks: total } = job;
  const finished = JobStatusRules.finishedCount(tasks);
  const percent = (count: number) => (total > 0 ? (count / total) * 100 : 0);
  const durationSeconds =
    job.started_at && job.finished_at
      ? (new Date(job.finished_at).getTime() -
          new Date(job.started_at).getTime()) /
        1000
      : null;

  return (
    <Card withBorder padding="lg">
      <Stack gap="md">
        <Group justify="space-between">
          <Group gap="sm">
            <Text fw={600}>Enrichment</Text>
            <StatusBadge status={job.status} />
          </Group>
          <Text size="sm" c="dimmed">
            {Format.integer(finished)} of {Format.integer(total)} stores
            finished
          </Text>
        </Group>

        <Progress.Root size="xl" aria-label="Enrichment progress">
          <Progress.Section
            value={percent(tasks.succeeded)}
            color={STATUS_COLOURS.succeeded}
          />
          <Progress.Section
            value={percent(tasks.failed)}
            color={STATUS_COLOURS.failed}
          />
          <Progress.Section
            value={percent(tasks.retrying)}
            color={STATUS_COLOURS.retrying}
          />
          <Progress.Section
            value={percent(tasks.in_progress)}
            color={STATUS_COLOURS.in_progress}
            animated
          />
        </Progress.Root>

        <SimpleGrid cols={{ base: 2, sm: 5 }}>
          <Count
            label="Succeeded"
            value={tasks.succeeded}
            colour={STATUS_COLOURS.succeeded}
          />
          <Count
            label="Failed"
            value={tasks.failed}
            colour={STATUS_COLOURS.failed}
          />
          <Count
            label="In progress"
            value={tasks.in_progress}
            colour={STATUS_COLOURS.in_progress}
          />
          <Count
            label="Retrying"
            value={tasks.retrying}
            colour={STATUS_COLOURS.retrying}
          />
          <Count
            label="Pending"
            value={tasks.pending}
            colour={STATUS_COLOURS.pending}
          />
        </SimpleGrid>

        <Group gap="xl" className={classes.timings}>
          <Text size="sm">Started: {Format.dateTime(job.started_at)}</Text>
          <Text size="sm">Finished: {Format.dateTime(job.finished_at)}</Text>
          {durationSeconds !== null && (
            <Text size="sm">Took: {Format.duration(durationSeconds)}</Text>
          )}
        </Group>

        {job.error && (
          <Alert color="red" title="The job failed">
            {job.error}
          </Alert>
        )}
      </Stack>
    </Card>
  );
}

function Count({
  label,
  value,
  colour,
}: {
  label: string;
  value: number;
  colour: string;
}) {
  return (
    <div>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text size="xl" fw={700} c={colour}>
        {Format.integer(value)}
      </Text>
    </div>
  );
}
