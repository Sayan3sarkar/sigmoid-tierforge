import type { JobStoreFilters } from "@/api/types";

import { TASK_STATUSES, TIERS } from "./status";

/** Reading and writing list state (page, filters) in the URL's search params. */
export class SearchParams {
  /** `?page=3` → 3; missing or invalid → 1. */
  static readPage(params: URLSearchParams): number {
    const page = Number(params.get("page"));
    return Number.isInteger(page) && page >= 1 ? page : 1;
  }

  /** `?status=failed&tier=large` → filters; unknown values are ignored. */
  static readStoreFilters(params: URLSearchParams): JobStoreFilters {
    const status = params.get("status");
    const tier = params.get("tier");
    return {
      status: TASK_STATUSES.find((value) => value === status),
      tier: TIERS.find((value) => value === tier),
    };
  }

  /** Filters and page as search params, leaving out defaults. */
  static forStoreList(
    filters: JobStoreFilters,
    page: number,
  ): Record<string, string> {
    const params: Record<string, string> = {};
    if (filters.status) params.status = filters.status;
    if (filters.tier) params.tier = filters.tier;
    if (page > 1) params.page = String(page);
    return params;
  }
}
