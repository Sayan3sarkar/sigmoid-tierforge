import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { makeJob, makeSummary } from '@/test/fixtures'
import { renderRoute } from '@/test/render'
import { apiUrl, server } from '@/test/server'

const CSV = new File(
  ['store_id,store_name,address,city,state,country\nST1,A,B,C,D,India\n'],
  'stores.csv',
  { type: 'text/csv' },
)

function fileInput(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[type="file"]') as HTMLInputElement
}

describe('UploadPage', () => {
  it('uploads the file and opens the new job', async () => {
    server.use(
      http.post(apiUrl('/uploads'), () =>
        HttpResponse.json(
          { upload_id: 'u-1', row_count: 1, job_id: 7, job_status: 'running' },
          { status: 201 },
        ),
      ),
      http.get(apiUrl('/jobs/7'), () => HttpResponse.json(makeJob({ status: 'running' }))),
      http.get(apiUrl('/jobs/7/summary'), () => HttpResponse.json(makeSummary())),
      http.get(apiUrl('/jobs/7/stores'), () => HttpResponse.json({ items: [], total_count: 0 })),
    )
    const { container, router } = renderRoute('/upload')

    await userEvent.upload(fileInput(container), CSV)

    await waitFor(() => expect(router.state.location.pathname).toBe('/jobs/7'))
    expect(await screen.findByRole('heading', { name: 'Job #7' })).toBeInTheDocument()
  })

  it('lists every problem when the API rejects the file', async () => {
    server.use(
      http.post(apiUrl('/uploads'), () =>
        HttpResponse.json(
          {
            detail: '2 invalid row(s); no stores were saved.',
            errors: [
              { field: null, message: 'Row 3: empty city' },
              { field: null, message: 'Row 5: duplicate store_id ST1 (first seen in row 2)' },
            ],
          },
          { status: 422 },
        ),
      ),
    )
    const { container, router } = renderRoute('/upload')

    await userEvent.upload(fileInput(container), CSV)

    expect(await screen.findByText('Row 3: empty city')).toBeInTheDocument()
    expect(screen.getByText('Row 5: duplicate store_id ST1 (first seen in row 2)')).toBeInTheDocument()
    expect(screen.getByText('2 invalid row(s); no stores were saved.')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/upload')
  })
})
