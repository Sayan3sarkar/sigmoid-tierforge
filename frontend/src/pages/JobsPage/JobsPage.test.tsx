import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { renderRoute } from '@/test/render'
import { apiUrl, server } from '@/test/server'

describe('JobsPage', () => {
  it('lists jobs with links to each one', async () => {
    server.use(
      http.get(apiUrl('/jobs'), () =>
        HttpResponse.json({
          items: [
            {
              job_id: 7,
              upload_id: 'u-1',
              status: 'running',
              total_tasks: 5000,
              created_at: '2026-10-23T18:26:20Z',
              finished_at: null,
            },
          ],
          total_count: 1,
        }),
      ),
    )
    renderRoute('/jobs')

    const link = await screen.findByRole('link', { name: 'Job #7' })
    expect(link).toHaveAttribute('href', '/jobs/7')
    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText('5,000')).toBeInTheDocument()
  })

  it('points to the upload page when there are no jobs', async () => {
    server.use(http.get(apiUrl('/jobs'), () => HttpResponse.json({ items: [], total_count: 0 })))
    renderRoute('/jobs')

    expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument()
  })

  it('redirects / to the jobs list', async () => {
    server.use(http.get(apiUrl('/jobs'), () => HttpResponse.json({ items: [], total_count: 0 })))
    const { router } = renderRoute('/')

    await screen.findByText(/No jobs yet/)
    expect(router.state.location.pathname).toBe('/jobs')
  })
})
