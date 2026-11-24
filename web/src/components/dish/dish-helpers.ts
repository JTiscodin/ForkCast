// Shared tiny helpers for the dish components.

/** Format a number as Indian Rupees with thousands separators (₹1,299). */
export function formatINR(n: number): string {
  const rounded = Math.round(n);
  return "₹" + rounded.toLocaleString("en-IN");
}
