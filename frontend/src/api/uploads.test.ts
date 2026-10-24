import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { apiUrl, server } from '@/test/server'

import { uploadStores } from './uploads'

const CSV = 'store_id,store_name,address,city,state,country\nST1,A,B,C,D,India\n'

describe('uploads API', () => {
  it('sends the file as multipart form data', async () => {
    let received: File | null = null
    server.use(
      http.post(apiUrl('/uploads'), async ({ request }) => {
        received = (await request.formData()).get('file') as File
        return HttpResponse.json(
          { upload_id: 'u-1', row_count: 1, job_id: 9, job_status: 'running' },
          { status: 201 },
        )
      }),
    )

    const result = await uploadStores(new File([CSV], 'stores.csv', { type: 'text/csv' }))

    expect(result.job_id).toBe(9)
    expect(received).not.toBeNull()
    expect(received!.name).toBe('stores.csv')
    expect(await received!.text()).toBe(CSV)
  })

  it('rejects with every problem the API listed', async () => {
    server.use(
      http.post(apiUrl('/uploads'), () =>
        HttpResponse.json(
          {
            detail: 'Invalid header.',
            errors: [{ field: null, message: 'Missing columns: country' }],
          },
          { status: 422 },
        ),
      ),
    )

    await expect(
      uploadStores(new File(['bad'], 'stores.csv', { type: 'text/csv' })),
    ).rejects.toMatchObject({
      status: 422,
      errors: [{ field: null, message: 'Missing columns: country' }],
    })
  })
})
