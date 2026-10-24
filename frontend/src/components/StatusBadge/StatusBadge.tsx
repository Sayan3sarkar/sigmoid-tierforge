import { Badge } from '@mantine/core'

import type { JobStatus, TaskStatus } from '@/api/types'
import { Format } from '@/utils/format'
import { STATUS_COLOURS } from '@/utils/status'

interface Props {
  status: JobStatus | TaskStatus
}

/** A job or task status as a coloured badge. */
export function StatusBadge({ status }: Props) {
  return (
    <Badge color={STATUS_COLOURS[status]} variant="light">
      {Format.label(status)}
    </Badge>
  )
}
