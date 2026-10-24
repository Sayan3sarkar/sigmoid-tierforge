import { describe, expect, it } from 'vitest'

import type { ScoringConfig } from '@/api/types'

import { DEFAULT_SCORING_CONFIG, ScoringRules } from './scoring'

function withChanges(changes: Partial<ScoringConfig>): ScoringConfig {
  return { ...DEFAULT_SCORING_CONFIG, ...changes }
}

describe('ScoringRules.validate', () => {
  it('accepts the brief’s example', () => {
    expect(ScoringRules.validate(DEFAULT_SCORING_CONFIG)).toEqual({})
  })

  it('requires weights that add up to 100', () => {
    const config = withChanges({ weights: { footfall: 50, revenue: 30, size_sqft: 30 } })

    expect(ScoringRules.validate(config)).toEqual({
      weights: 'Weights must add up to 100, not 110',
    })
  })

  it('rejects a weight outside 0–100 or a negative bar', () => {
    const config = withChanges({
      weights: { footfall: 101, revenue: -1, size_sqft: 0 },
      bars: { footfall: 15000, revenue: -1, size_sqft: 8000 },
    })

    const errors = ScoringRules.validate(config)
    expect(errors['weights.footfall']).toBeDefined()
    expect(errors['weights.revenue']).toBeDefined()
    expect(errors['bars.revenue']).toBe('Must be 0 or more')
  })

  it('rejects Medium above Large, and accepts them equal', () => {
    expect(
      ScoringRules.validate(withChanges({ tiers: { large_min: 40, medium_min: 70 } })).tiers,
    ).toBe('Medium (70) must not be above Large (40)')
    expect(ScoringRules.validate(withChanges({ tiers: { large_min: 50, medium_min: 50 } }))).toEqual(
      {},
    )
  })
})
