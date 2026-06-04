import type { CSSProperties } from "react";

export type CanonicalReviewStatus = "approved" | "needs_review" | "needs_edit" | "rejected" | "suggested";

export function normalizeReviewStatus(status: string): CanonicalReviewStatus {
  if (status === "reviewed" || status === "approved") return "approved";
  if (status === "needs_edit") return "needs_edit";
  if (status === "rejected") return "rejected";
  if (status === "suggested") return "suggested";
  return "needs_review";
}

export function reviewStatusLabel(status: string) {
  const normalized = normalizeReviewStatus(status);
  const labels: Record<CanonicalReviewStatus, string> = {
    approved: "Approved",
    needs_review: "Needs Review",
    needs_edit: "Needs Edit",
    rejected: "Rejected",
    suggested: "AI Suggested"
  };
  return labels[normalized];
}

export function ReviewStatusBadge({ status }: { status: string }) {
  const normalized = normalizeReviewStatus(status);
  return <span className={`review-status-badge status-${normalized}`}>{reviewStatusLabel(status)}</span>;
}

export function ReviewTypeChip({ label, color }: { label: string; color?: string }) {
  return (
    <span className="review-type-chip" style={color ? { "--chip-color": color } as CSSProperties : undefined}>
      {label}
    </span>
  );
}

export function ReviewConfidence({ value }: { value: number }) {
  return <span className="review-confidence">{Math.round(value * 100)}%</span>;
}
