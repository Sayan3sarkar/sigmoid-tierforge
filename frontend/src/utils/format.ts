const integerFormat = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 0,
});
const moneyFormat = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "medium",
});

export class Format {
  /** 18234 → "18,234"; null → "—". */
  static integer(value: number | null | undefined): string {
    return value == null ? "—" : integerFormat.format(value);
  }

  /**
   * The API sends revenue as an exact decimal string ("142033.50"); this is
   * the one place it becomes a number. Returns null for null or invalid input.
   */
  static parseRevenue(value: string | null | undefined): number | null {
    if (value == null || value.trim() === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  /** "142033.5" → "1,42,033.50"; null → "—". */
  static revenue(value: string | null | undefined): string {
    const parsed = Format.parseRevenue(value);
    return parsed == null ? "—" : moneyFormat.format(parsed);
  }

  /** ISO timestamp → local date and time; null → "—". */
  static dateTime(value: string | null | undefined): string {
    return value == null ? "—" : dateTimeFormat.format(new Date(value));
  }

  /** Seconds → "18m 35s" / "42s" / "1h 2m". */
  static duration(totalSeconds: number): string {
    const seconds = Math.max(0, Math.round(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const rest = seconds % 60;
    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${rest}s`;
    return `${rest}s`;
  }

  /** "completed_with_failures" → "Completed with failures". */
  static label(value: string): string {
    const words = value.replaceAll("_", " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
}
