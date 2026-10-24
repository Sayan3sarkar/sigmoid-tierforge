import { Badge } from '@mantine/core'

import type { Tier } from '@/api/types'
import { Format } from '@/utils/format'
import { TIER_COLOURS } from '@/utils/status'

interface Props {
  tier: Tier
}

/** A tier (Large / Medium / Small) as a coloured badge. */
export function TierBadge({ tier }: Props) {
  return (
    <Badge color={TIER_COLOURS[tier]} variant="filled">
      {Format.label(tier)}
    </Badge>
  )
}
