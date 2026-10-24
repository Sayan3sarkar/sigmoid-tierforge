import { Skeleton, Table, Text } from '@mantine/core'

import type { JobStoreItem } from '@/api/types'
import { StatusBadge } from '@/components/StatusBadge'
import { TierBadge } from '@/components/TierBadge'
import { Format } from '@/utils/format'

import classes from './StoreTable.module.css'

interface Props {
  items: JobStoreItem[]
  loading?: boolean
}

const COLUMNS = [
  'Store',
  'Location',
  'Status',
  'Footfall',
  'Revenue',
  'Size (sqft)',
  'Score',
  'Tier',
  'Failure reason',
]

/** A page of a job's stores: status, metrics, score, tier and failure reason. */
export function StoreTable({ items, loading = false }: Props) {
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table striped highlightOnHover verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            {COLUMNS.map((column) => (
              <Table.Th key={column}>{column}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {loading && items.length === 0 ? (
            <LoadingRows />
          ) : items.length === 0 ? (
            <Table.Tr>
              <Table.Td colSpan={COLUMNS.length}>
                <Text c="dimmed" ta="center" py="md">
                  No stores match these filters.
                </Text>
              </Table.Td>
            </Table.Tr>
          ) : (
            items.map((store) => (
              <Table.Tr key={store.task_id}>
                <Table.Td>
                  <Text size="sm" fw={500}>
                    {store.store_name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {store.store_id}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{store.city}</Text>
                  <Text size="xs" c="dimmed">
                    {store.state}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <StatusBadge status={store.status} />
                </Table.Td>
                <Table.Td className={classes.number}>
                  {Format.integer(store.estimated_monthly_footfall)}
                </Table.Td>
                <Table.Td className={classes.number}>
                  {Format.revenue(store.estimated_monthly_revenue)}
                </Table.Td>
                <Table.Td className={classes.number}>
                  {Format.integer(store.store_size_sqft)}
                </Table.Td>
                <Table.Td className={classes.number}>{store.score ?? '—'}</Table.Td>
                <Table.Td>{store.tier ? <TierBadge tier={store.tier} /> : '—'}</Table.Td>
                <Table.Td>
                  <Text size="sm" c={store.last_error ? 'red' : 'dimmed'}>
                    {store.last_error ?? '—'}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))
          )}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}

function LoadingRows() {
  return Array.from({ length: 5 }, (_, row) => (
    <Table.Tr key={row}>
      {COLUMNS.map((column) => (
        <Table.Td key={column}>
          <Skeleton height={16} />
        </Table.Td>
      ))}
    </Table.Tr>
  ))
}
