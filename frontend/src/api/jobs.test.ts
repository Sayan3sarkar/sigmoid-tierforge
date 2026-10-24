import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { apiUrl, server } from '@/test/server'
import { makeJob, makeScoringResponse, makeStore, SCORING_CONFIG } from '@/test/fixtures'

import { ApiError } from './errors'
import { getJob, listJobs, listJobStores, scoreJob } from './jobs'

describe('jobs API', () => {
  it('lists jobs with page and page_size', async () => {
    let query: URLSearchParams | undefined
    server.use(
      http.get(apiUrl('/jobs'), ({ request }) => {
        query = new URL(request.url).searchParams
        return HttpResponse.json({ items: [], total_count: 0 })
      }),
    )

    const page = await listJobs({ page: 2, pageSize: 20 })

    expect(page).toEqual({ items: [], total_count: 0 })
    expect(query?.get('page')).toBe('2')
    expect(query?.get('page_size')).toBe('20')
  })

  it('gets a job', async () => {
    server.use(http.get(apiUrl('/jobs/7'), () => HttpResponse.json(makeJob())))

    expect(await getJob(7)).toEqual(makeJob())
  })

  it('sends only the filters that are set', async () => {
    let query: URLSearchParams | undefined
    server.use(
      http.get(apiUrl('/jobs/7/stores'), ({ request }) => {
        query = new URL(request.url).searchParams
        return HttpResponse.json({ items: [makeStore()], total_count: 1 })
      }),
    )

    const page = await listJobStores(7, { tier: 'large' }, { page: 1, pageSize: 25 })

    expect(page.items).toHaveLength(1)
    expect(query?.get('tier')).toBe('large')
    expect(query?.has('status')).toBe(false)
    expect(query?.get('page_size')).toBe('25')
  })

  it('posts the scoring settings as JSON', async () => {
    let body: unknown
    server.use(
      http.post(apiUrl('/jobs/7/scoring'), async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(makeScoringResponse())
      }),
    )

    const result = await scoreJob(7, SCORING_CONFIG)

    expect(body).toEqual(SCORING_CONFIG)
    expect(result.tiers).toEqual({ large: 1, medium: 1, small: 1 })
  })

  it('rejects with an ApiError carrying the API’s errors', async () => {
    server.use(
      http.post(apiUrl('/jobs/7/scoring'), () =>
        HttpResponse.json(
          {
            detail: 'Invalid request.',
            errors: [{ field: 'weights', message: 'weights must add up to 100, not 110' }],
          },
          { status: 422 },
        ),
      ),
    )

    const error = await scoreJob(7, SCORING_CONFIG).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
    expect((error as ApiError).fieldErrors()).toEqual({
      weights: 'weights must add up to 100, not 110',
    })
  })

  it('rejects with a 404 ApiError for an unknown job', async () => {
    server.use(
      http.get(apiUrl('/jobs/999'), () =>
        HttpResponse.json({ detail: 'Job 999 not found.', errors: [] }, { status: 404 }),
      ),
    )

    await expect(getJob(999)).rejects.toMatchObject({ status: 404, detail: 'Job 999 not found.' })
  })

  it('rejects with a status-less ApiError when the API is unreachable', async () => {
    server.use(http.get(apiUrl('/jobs/7'), () => HttpResponse.error()))

    await expect(getJob(7)).rejects.toMatchObject({ status: null })
  })
})
