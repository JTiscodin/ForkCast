// Formatting + math helpers for the wallet widget & approve bar.

/**
 * Format a number as Indian Rupees with thousands separators.
 * Uses the en-IN locale grouping (lakh/crore style) and no decimals by default.
 *
 *   formatINR(1234567)  -> "₹12,34,567"
 *   formatINR(-450)     -> "-₹450"
 *   formatINR(0)        -> "₹0"
 */
export function formatINR(n: number, opts?: { decimals?: number }): string {
  const value = Number.isFinite(n) ? n : 0;
  const decimals = opts?.decimals ?? 0;
  const negative = value < 0;
  const abs = Math.abs(value);
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(abs);
  return `${negative ? "-" : ""}₹${formatted}`;
}

/**
 * Percentage of `part` out of `total`, clamped to [0, 100].
 * Returns 0 when total is 0 or invalid.
 *
 *   pct(50, 200) -> 25
 *   pct(300, 200) -> 100  (clamped)
 */
export function pct(part: number, total: number): number {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) return 0;
  const raw = (part / total) * 100;
  if (raw < 0) return 0;
  if (raw > 100) return 100;
  return raw;
}
