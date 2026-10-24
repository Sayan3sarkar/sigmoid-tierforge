import { describe, expect, it } from 'vitest'

import { Format } from './format'

describe('Format', () => {
  it('formats integers, and null as a dash', () => {
    expect(Format.integer(18234)).toBe('18,234')
    expect(Format.integer(null)).toBe('—')
  })

  it('parses the API revenue string into a number', () => {
    expect(Format.parseRevenue('142033.50')).toBe(142033.5)
    expect(Format.parseRevenue(null)).toBeNull()
    expect(Format.parseRevenue('')).toBeNull()
    expect(Format.parseRevenue('not a number')).toBeNull()
  })

  it('formats revenue with two decimals', () => {
    expect(Format.revenue('142033.5')).toBe('1,42,033.50')
    expect(Format.revenue(null)).toBe('—')
  })

  it('formats durations', () => {
    expect(Format.duration(42)).toBe('42s')
    expect(Format.duration(1115)).toBe('18m 35s')
    expect(Format.duration(3720)).toBe('1h 2m')
  })

  it('turns enum values into labels', () => {
    expect(Format.label('completed_with_failures')).toBe('Completed with failures')
    expect(Format.label('large')).toBe('Large')
  })
})
