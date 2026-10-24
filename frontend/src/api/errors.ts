import { isAxiosError } from 'axios'

import type { ErrorItem, ErrorResponse } from './types'

/**
 * Every failed API call becomes an ApiError, so the rest of the app never
 * handles raw axios errors.
 */
export class ApiError extends Error {
  /** HTTP status, or null when there was no response (network error, timeout). */
  readonly status: number | null
  /** The backend's `detail`, or a generic message. */
  readonly detail: string
  /** The backend's list of problems: `[{ field, message }]`. */
  readonly errors: ErrorItem[]

  constructor(status: number | null, detail: string, errors: ErrorItem[] = []) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.errors = errors
  }

  /** Problems that belong to one input, keyed by field: `{ weights: '…' }`. */
  fieldErrors(): Record<string, string> {
    const byField: Record<string, string> = {}
    for (const error of this.errors) {
      if (error.field && !(error.field in byField)) byField[error.field] = error.message
    }
    return byField
  }

  /** Problems that don't belong to one input (e.g. CSV rows). */
  generalErrors(): string[] {
    return this.errors.filter((error) => !error.field).map((error) => error.message)
  }

  static from(error: unknown): ApiError {
    if (error instanceof ApiError) return error
    if (!isAxiosError(error)) {
      return new ApiError(null, error instanceof Error ? error.message : 'Unexpected error.')
    }
    if (!error.response) {
      const detail =
        error.code === 'ECONNABORTED'
          ? 'The request timed out.'
          : `Can't reach the API at ${error.config?.baseURL ?? 'the configured URL'}.`
      return new ApiError(null, detail)
    }
    const { status, data } = error.response
    if (isErrorResponse(data)) return new ApiError(status, data.detail, data.errors ?? [])
    return new ApiError(status, `Request failed with status ${status}.`)
  }
}

function isErrorResponse(data: unknown): data is ErrorResponse {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as { detail?: unknown }).detail === 'string'
  )
}
