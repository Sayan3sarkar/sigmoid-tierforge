import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { ApiError } from './errors'

function axiosErrorWith(status: number, data: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('failed', 'ERR_BAD_REQUEST', config, null, {
    status,
    statusText: '',
    headers: {},
    config,
    data,
  })
}

describe('ApiError', () => {
  it('reads the API’s error body', () => {
    const error = ApiError.from(
      axiosErrorWith(422, {
        detail: 'Invalid request.',
        errors: [
          { field: 'weights', message: 'weights must add up to 100, not 110' },
          { field: null, message: 'Row 12: empty city' },
        ],
      }),
    )

    expect(error.status).toBe(422)
    expect(error.detail).toBe('Invalid request.')
    expect(error.fieldErrors()).toEqual({ weights: 'weights must add up to 100, not 110' })
    expect(error.generalErrors()).toEqual(['Row 12: empty city'])
  })

  it('falls back to a generic message for an unexpected body', () => {
    const error = ApiError.from(axiosErrorWith(502, '<html>Bad gateway</html>'))

    expect(error.status).toBe(502)
    expect(error.detail).toBe('Request failed with status 502.')
    expect(error.errors).toEqual([])
  })

  it('has no status when there was no response', () => {
    const error = ApiError.from(
      new AxiosError('Network Error', 'ERR_NETWORK', {
        headers: new AxiosHeaders(),
        baseURL: 'http://localhost:8001/api',
      }),
    )

    expect(error.status).toBeNull()
    expect(error.detail).toBe("Can't reach the API at http://localhost:8001/api.")
  })

  it('wraps a non-axios error', () => {
    expect(ApiError.from(new Error('boom')).detail).toBe('boom')
  })
})
