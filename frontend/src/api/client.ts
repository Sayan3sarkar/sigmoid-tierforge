import axios from 'axios'

import { ApiError } from './errors'

/** Backend URL without the /api suffix, from VITE_API_BASE_URL. */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8001'

/** Every call except the upload returns in well under a second. */
const DEFAULT_TIMEOUT_MS = 15_000

/** The one axios instance used for every API call. */
export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api`,
  timeout: DEFAULT_TIMEOUT_MS,
  headers: { Accept: 'application/json' },
})

// Turn every failure into an ApiError, so callers never see raw axios errors.
apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(ApiError.from(error)),
)
