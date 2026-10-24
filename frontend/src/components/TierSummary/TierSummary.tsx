import { Card, Group, SimpleGrid, Stack, Text } from '@mantine/core'

import type { ScoringSummary } from '@/api/types'
import { TierBadge } from '@/components/TierBadge'
import { Format } from '@/utils/format'
import { TIERS } from '@/utils/status'

interface Props {
  /** The job's latest scoring, or null if it hasn't been scored. */
  scoring: ScoringSummary | null
}

/** Large / Medium / Small counts from the latest scoring, and when it ran. */
export function TierSummary({ scoring }: Props) {
  if (!scoring) {
    return (
      <Text c="dimmed" size="sm">
        Not scored yet. Set the bars, weights and thresholds above, then score the stores.
      </Text>
    )
  }

  const { tiers } = scoring
  const total = tiers.large + tiers.medium + tiers.small

  return (
    <Stack gap="sm">
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        {TIERS.map((tier) => (
          <Card key={tier} withBorder padding="md">
            <Group justify="space-between">
              <TierBadge tier={tier} />
              <Text size="sm" c="dimmed">
                {total > 0 ? `${Math.round((tiers[tier] / total) * 100)}%` : '—'}
              </Text>
            </Group>
            <Text size="xl" fw={700} mt="sm" aria-label={`${tier} stores`}>
              {Format.integer(tiers[tier])}
            </Text>
          </Card>
        ))}
      </SimpleGrid>
      <Text size="sm" c="dimmed">
        {Format.integer(total)} stores scored on {Format.dateTime(scoring.scored_at)}
      </Text>
    </Stack>
  )
}
