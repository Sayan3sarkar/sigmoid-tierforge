import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'

import { Providers } from '@/Providers'
import { createQueryClient } from '@/queryClient'
import { routes } from '@/router'

function testQueryClient() {
  const client = createQueryClient()
  // Fail fast in tests: no retries.
  client.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
  return client
}

/** Render one component inside the app's providers. */
export function renderWithProviders(ui: ReactElement) {
  const queryClient = testQueryClient()
  return { queryClient, ...render(<Providers queryClient={queryClient}>{ui}</Providers>) }
}

/** Render the whole app at `path`, with the real routes and a memory router. */
export function renderRoute(path: string) {
  const queryClient = testQueryClient()
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const view = render(
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return { queryClient, router, ...view }
}
