import { Group, Pagination, Text } from '@mantine/core'

import { Format } from '@/utils/format'

interface Props {
  page: number
  pageSize: number
  totalCount: number
  onChange: (page: number) => void
}

/** "Showing 51–100 of 601" and page buttons. */
export function TablePagination({ page, pageSize, totalCount, onChange }: Props) {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const first = totalCount === 0 ? 0 : (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, totalCount)

  return (
    <Group justify="space-between">
      <Text size="sm" c="dimmed">
        Showing {Format.integer(first)}–{Format.integer(last)} of {Format.integer(totalCount)}
      </Text>
      <Pagination total={totalPages} value={page} onChange={onChange} withEdges size="sm" />
    </Group>
  )
}
