import { describe, expect, it } from 'vitest'

import { SearchParams } from './searchParams'

describe('SearchParams', () => {
  it('reads the page, defaulting to 1', () => {
    expect(SearchParams.readPage(new URLSearchParams('page=3'))).toBe(3)
    expect(SearchParams.readPage(new URLSearchParams(''))).toBe(1)
    expect(SearchParams.readPage(new URLSearchParams('page=0'))).toBe(1)
    expect(SearchParams.readPage(new URLSearchParams('page=abc'))).toBe(1)
  })

  it('reads known filters and ignores unknown values', () => {
    expect(SearchParams.readStoreFilters(new URLSearchParams('status=failed&tier=large'))).toEqual({
      status: 'failed',
      tier: 'large',
    })
    expect(SearchParams.readStoreFilters(new URLSearchParams('status=huge&tier=xl'))).toEqual({
      status: undefined,
      tier: undefined,
    })
  })

  it('writes only non-default values', () => {
    expect(SearchParams.forStoreList({ status: 'failed' }, 1)).toEqual({ status: 'failed' })
    expect(SearchParams.forStoreList({ tier: 'small' }, 3)).toEqual({ tier: 'small', page: '3' })
  })
})
