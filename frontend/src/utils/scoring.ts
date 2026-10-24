import type { ScoringConfig } from "@/api/types";

/** The brief's worked example: a sensible starting point for a new job. */
export const DEFAULT_SCORING_CONFIG: ScoringConfig = {
  bars: { footfall: 15000, revenue: 150000, size_sqft: 8000 },
  weights: { footfall: 50, revenue: 30, size_sqft: 20 },
  tiers: { large_min: 70, medium_min: 40 },
};

export class ScoringRules {
  /**
   * The API's validation, checked in the browser first so most mistakes never
   * reach the server. Keys match the API's error fields ("weights",
   * "bars.revenue", …), so server and client errors land on the same inputs.
   */
  static validate(config: ScoringConfig): Record<string, string> {
    const errors: Record<string, string> = {};
    const { bars, weights, tiers } = config;

    for (const [metric, value] of Object.entries(bars)) {
      if (!Number.isFinite(value) || value < 0)
        errors[`bars.${metric}`] = "Must be 0 or more";
    }
    for (const [metric, value] of Object.entries(weights)) {
      if (!Number.isInteger(value) || value < 0 || value > 100) {
        errors[`weights.${metric}`] = "Must be a whole number from 0 to 100";
      }
    }
    const total = ScoringRules.weightTotal(config);
    if (total !== 100)
      errors.weights = `Weights must add up to 100, not ${total}`;

    for (const [name, value] of Object.entries(tiers)) {
      if (!Number.isInteger(value) || value < 0 || value > 100) {
        errors[`tiers.${name}`] = "Must be a whole number from 0 to 100";
      }
    }
    if (tiers.medium_min > tiers.large_min) {
      errors.tiers = `Medium (${tiers.medium_min}) must not be above Large (${tiers.large_min})`;
    }
    return errors;
  }

  static weightTotal(config: ScoringConfig): number {
    const { footfall, revenue, size_sqft } = config.weights;
    return (footfall || 0) + (revenue || 0) + (size_sqft || 0);
  }
}
