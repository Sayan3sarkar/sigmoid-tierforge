import { Group, SegmentedControl, Stack, Text } from '@mantine/core'

import type { JobStoreFilters, TaskStatus, Tier } from '@/api/types'
import { Format } from '@/utils/format'
import { TASK_STATUSES, TIERS } from '@/utils/status'

interface Props {
  filters: JobStoreFilters
  onChange: (filters: JobStoreFilters) => void
}

const ALL = 'all'

/** Status and tier filters for a job's store list. */
export function StoreFilters({ filters, onChange }: Props) {
  return (
    <Group gap="xl" align="flex-end" wrap="wrap">
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Status
        </Text>
        <SegmentedControl
          aria-label="Filter by status"
          value={filters.status ?? ALL}
          onChange={(value) =>
            onChange({ ...filters, status: value === ALL ? undefined : (value as TaskStatus) })
          }
          data={[
            { value: ALL, label: 'All' },
            ...TASK_STATUSES.map((status) => ({ value: status, label: Format.label(status) })),
          ]}
        />
      </Stack>
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Tier
        </Text>
        <SegmentedControl
          aria-label="Filter by tier"
          value={filters.tier ?? ALL}
          onChange={(value) =>
            onChange({ ...filters, tier: value === ALL ? undefined : (value as Tier) })
          }
          data={[
            { value: ALL, label: 'All' },
            ...TIERS.map((tier) => ({ value: tier, label: Format.label(tier) })),
          ]}
        />
      </Stack>
    </Group>
  )
}
