import { apiClient } from './client'
import type {
  Job,
  JobListPage,
  JobStoreFilters,
  JobStorePage,
  JobSummary,
  PageParams,
  ScoringConfig,
  ScoringResponse,
} from './types'

/** GET /api/jobs: jobs, newest first. */
export async function listJobs(page: PageParams): Promise<JobListPage> {
  const { data } = await apiClient.get<JobListPage>('/jobs', {
    params: { page: page.page, page_size: page.pageSize },
  })
  return data
}

/** GET /api/jobs/{id}: the job and its task counts per status. */
export async function getJob(jobId: number): Promise<Job> {
  const { data } = await apiClient.get<Job>(`/jobs/${jobId}`)
  return data
}

/** GET /api/jobs/{id}/summary: progress and the latest scoring. */
export async function getJobSummary(jobId: number): Promise<JobSummary> {
  const { data } = await apiClient.get<JobSummary>(`/jobs/${jobId}/summary`)
  return data
}

/** GET /api/jobs/{id}/stores: one page of the job's stores, filtered. */
export async function listJobStores(
  jobId: number,
  filters: JobStoreFilters,
  page: PageParams,
): Promise<JobStorePage> {
  const { data } = await apiClient.get<JobStorePage>(`/jobs/${jobId}/stores`, {
    params: {
      status: filters.status,
      tier: filters.tier,
      page: page.page,
      page_size: page.pageSize,
    },
  })
  return data
}

/** POST /api/jobs/{id}/scoring: score the job with these settings. */
export async function scoreJob(jobId: number, config: ScoringConfig): Promise<ScoringResponse> {
  const { data } = await apiClient.post<ScoringResponse>(`/jobs/${jobId}/scoring`, config)
  return data
}
