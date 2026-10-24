import { setupServer } from 'msw/node'

import { API_BASE_URL } from '@/api/client'

/** The mock API: tests add handlers with `server.use(...)`. */
export const server = setupServer()

/** Full URL of an API path, as the axios client calls it: apiUrl('/jobs/1'). */
export function apiUrl(path: string): string {
  return `${API_BASE_URL}/api${path}`
}
