import { apiClient } from './client'
import type { UploadResponse } from './types'

/** Saving and queueing 5,000 stores takes a couple of seconds; allow headroom. */
const UPLOAD_TIMEOUT_MS = 60_000

/** POST /api/uploads: upload a store CSV and start its enrichment job. */
export async function uploadStores(file: File): Promise<UploadResponse> {
  const body = new FormData()
  body.append('file', file)
  const { data } = await apiClient.post<UploadResponse>('/uploads', body, {
    timeout: UPLOAD_TIMEOUT_MS,
  })
  return data
}
