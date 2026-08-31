"use client";

import { Check, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

/** A single constraint chip: "paneer 45/10 ✓" or "paneer 6/10 ✗". */
export function ConstraintChip({
  tag,
  got,
  needed,
}: {
  tag: string;
  got: number;
  needed: number;
}) {
  const met = got >= needed;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        met
          ? "border-success/25 bg-success/10 text-success"
          : "border-danger/25 bg-danger/10 text-danger"
      )}
    >
      <span className="capitalize">{tag}</span>
      <span className="tabular-nums opacity-90">
        {got}/{needed}
      </span>
      {met ? (
        <Check className="size-4" strokeWidth={2.4} aria-hidden />
      ) : (
        <TriangleAlert className="size-4" strokeWidth={2.4} aria-hidden />
      )}
    </span>
  );
}

export default ConstraintChip;
