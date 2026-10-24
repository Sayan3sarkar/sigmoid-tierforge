import { Button, Group, NumberInput, SimpleGrid, Stack, Text, Title } from '@mantine/core'
import { useForm } from '@mantine/form'

import { ApiError } from '@/api/errors'
import type { ScoringConfig } from '@/api/types'
import { ApiErrorAlert } from '@/components/ApiErrorAlert'
import { ScoringRules } from '@/utils/scoring'

import classes from './ScoringForm.module.css'

interface Props {
  initialConfig: ScoringConfig
  /** Submit to the API; a rejected ApiError's field problems are shown on their inputs. */
  onSubmit: (config: ScoringConfig) => Promise<unknown>
  submitting?: boolean
  /** The last submission's error, for problems that aren't about one input. */
  serverError?: ApiError | null
}

const METRICS = [
  { key: 'footfall', label: 'Monthly footfall' },
  { key: 'revenue', label: 'Monthly revenue' },
  { key: 'size_sqft', label: 'Store size (sqft)' },
] as const

/** Bars, weights and tier thresholds; checked in the browser, then by the API. */
export function ScoringForm({ initialConfig, onSubmit, submitting = false, serverError }: Props) {
  const form = useForm<ScoringConfig>({
    mode: 'controlled',
    initialValues: initialConfig,
    validate: (values) => ScoringRules.validate(values),
  })

  const handleSubmit = async (values: ScoringConfig) => {
    try {
      await onSubmit(values)
    } catch (error) {
      // Put the API's field errors ("weights", "bars.revenue", …) on the matching inputs.
      if (error instanceof ApiError) form.setErrors(error.fieldErrors())
    }
  }

  const weightTotal = ScoringRules.weightTotal(form.values)

  return (
    <form onSubmit={form.onSubmit(handleSubmit)} noValidate>
      <Stack gap="lg">
        <div>
          <Title order={5}>Bars and weights</Title>
          <Text size="sm" c="dimmed">
            A store earns a metric's weight when its value is at least the bar. Weights must add
            up to 100.
          </Text>
        </div>

        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          {METRICS.map((metric) => (
            <Stack key={metric.key} gap="xs" className={classes.metric}>
              <Text fw={600}>{metric.label}</Text>
              <NumberInput
                label="Bar"
                min={0}
                thousandSeparator=","
                {...form.getInputProps(`bars.${metric.key}`)}
              />
              <NumberInput
                label="Weight"
                min={0}
                max={100}
                allowDecimal={false}
                suffix="%"
                {...form.getInputProps(`weights.${metric.key}`)}
              />
            </Stack>
          ))}
        </SimpleGrid>

        <Text size="sm" c={weightTotal === 100 ? 'teal' : 'red'} role="status">
          Weights total: {weightTotal} / 100
        </Text>
        {form.errors.weights && (
          <Text size="sm" c="red">
            {form.errors.weights}
          </Text>
        )}

        <div>
          <Title order={5}>Tier thresholds</Title>
          <Text size="sm" c="dimmed">
            Score at least Large → Large; at least Medium → Medium; otherwise Small.
          </Text>
        </div>
        <SimpleGrid cols={{ base: 1, sm: 2 }} maw={480}>
          <NumberInput
            label="Large from"
            min={0}
            max={100}
            allowDecimal={false}
            {...form.getInputProps('tiers.large_min')}
          />
          <NumberInput
            label="Medium from"
            min={0}
            max={100}
            allowDecimal={false}
            {...form.getInputProps('tiers.medium_min')}
          />
        </SimpleGrid>
        {form.errors.tiers && (
          <Text size="sm" c="red">
            {form.errors.tiers}
          </Text>
        )}

        {serverError && <ApiErrorAlert error={serverError} title="Scoring failed" hideFieldErrors />}

        <Group>
          <Button type="submit" loading={submitting}>
            Score stores
          </Button>
        </Group>
      </Stack>
    </form>
  )
}
