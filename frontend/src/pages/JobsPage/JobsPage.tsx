import {
  Anchor,
  Button,
  Group,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { Link, useSearchParams } from "react-router";

import { ApiErrorAlert } from "@/components/ApiErrorAlert";
import { StatusBadge } from "@/components/StatusBadge";
import { TablePagination } from "@/components/TablePagination";
import { useJobs } from "@/hooks/useJobs";
import { Format } from "@/utils/format";
import { SearchParams } from "@/utils/searchParams";

const PAGE_SIZE = 20;

/** Every job, newest first. */
export function JobsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = SearchParams.readPage(searchParams);
  const jobs = useJobs({ page, pageSize: PAGE_SIZE });

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Title order={2}>Jobs</Title>
        <Button component={Link} to="/upload">
          Upload stores
        </Button>
      </Group>

      {jobs.error && (
        <ApiErrorAlert error={jobs.error} title="Couldn't load jobs" />
      )}

      {jobs.data && jobs.data.total_count === 0 ? (
        <Text c="dimmed">
          No jobs yet.{" "}
          <Anchor component={Link} to="/upload">
            Upload a store CSV
          </Anchor>{" "}
          to start one.
        </Text>
      ) : (
        <>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Job</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Stores</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th>Finished</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {jobs.data?.items.map((job) => (
                <Table.Tr key={job.job_id}>
                  <Table.Td>
                    <Anchor component={Link} to={`/jobs/${job.job_id}`}>
                      Job #{job.job_id}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge status={job.status} />
                  </Table.Td>
                  <Table.Td>{Format.integer(job.total_tasks)}</Table.Td>
                  <Table.Td>{Format.dateTime(job.created_at)}</Table.Td>
                  <Table.Td>{Format.dateTime(job.finished_at)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          {jobs.data && (
            <TablePagination
              page={page}
              pageSize={PAGE_SIZE}
              totalCount={jobs.data.total_count}
              onChange={(next) => setSearchParams({ page: String(next) })}
            />
          )}
        </>
      )}
    </Stack>
  );
}
