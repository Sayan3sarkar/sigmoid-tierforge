// Readable names for the API's types, generated from the backend's OpenAPI
// schema into schema.d.ts (`npm run api:types`). Import types from here, not
// from schema.d.ts.
import type { components } from './schema'

type Schemas = components['schemas']

export type JobStatus = Schemas['JobStatus']
export type TaskStatus = Schemas['TaskStatus']
export type Tier = Schemas['Tier']

export type Job = Schemas['JobResponse']
export type JobListItem = Schemas['JobListItem']
export type JobSummary = Schemas['JobSummary']
export type JobStoreItem = Schemas['JobStoreItem']
export type TaskCounts = Schemas['TaskCounts']
export type TierCounts = Schemas['TierCounts']

export type ScoringConfig = Schemas['ScoringConfig']
export type ScoringResponse = Schemas['ScoringResponse']
export type ScoringSummary = Schemas['ScoringSummary']

export type UploadResponse = Schemas['UploadResponse']

export type ErrorItem = Schemas['ErrorItem']
export type ErrorResponse = Schemas['ErrorResponse']

export type JobListPage = Schemas['Page_JobListItem_']
export type JobStorePage = Schemas['Page_JobStoreItem_']

/** `page` and `page_size` query parameters of a paginated list. */
export interface PageParams {
  page: number
  pageSize: number
}

/** Filters of a job's store list; both optional. */
export interface JobStoreFilters {
  status?: TaskStatus
  tier?: Tier
}
