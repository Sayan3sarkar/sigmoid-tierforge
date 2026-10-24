import type {
  Job,
  JobStoreItem,
  JobSummary,
  ScoringConfig,
  ScoringResponse,
} from '@/api/types'

export const SCORING_CONFIG: ScoringConfig = {
  bars: { footfall: 15000, revenue: 150000, size_sqft: 8000 },
  weights: { footfall: 50, revenue: 30, size_sqft: 20 },
  tiers: { large_min: 70, medium_min: 40 },
}

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    job_id: 7,
    upload_id: '96749189-df7a-4dd4-ac1b-59b29e50d5c2',
    status: 'completed_with_failures',
    error: null,
    total_tasks: 4,
    tasks: { pending: 0, in_progress: 0, succeeded: 3, failed: 1 },
    created_at: '2026-10-23T18:26:20Z',
    started_at: '2026-10-23T18:26:22Z',
    finished_at: '2026-10-23T18:44:57Z',
    ...overrides,
  }
}

export function makeSummary(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: 7,
    status: 'completed_with_failures',
    total_tasks: 4,
    tasks: { pending: 0, in_progress: 0, succeeded: 3, failed: 1 },
    scoring: null,
    ...overrides,
  }
}

export function makeStore(overrides: Partial<JobStoreItem> = {}): JobStoreItem {
  return {
    task_id: 101,
    store_id: 'ST000001',
    store_name: 'Fresh Supermarket #1',
    address: '71 Church Street',
    city: 'New Delhi',
    state: 'Delhi',
    status: 'succeeded',
    attempt_count: 1,
    last_error: null,
    estimated_monthly_footfall: 40000,
    estimated_monthly_revenue: '400000.00',
    store_size_sqft: 18000,
    score: 100,
    tier: 'large',
    finished_at: '2026-10-23T18:30:00Z',
    ...overrides,
  }
}

export function makeScoringResponse(overrides: Partial<ScoringResponse> = {}): ScoringResponse {
  return {
    job_id: 7,
    scored_count: 3,
    tiers: { large: 1, medium: 1, small: 1 },
    config: SCORING_CONFIG,
    scored_at: '2026-10-23T18:46:09Z',
    ...overrides,
  }
}
