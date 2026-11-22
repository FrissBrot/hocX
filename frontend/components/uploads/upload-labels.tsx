"use client";

import { useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import type { UploadItemStatus, UploadJob, UploadJobStatus } from "@/types/api";

export type UploadsT = (key: string, values?: Record<string, string | number | Date>) => string;

const STATUS_VARIANT: Record<UploadJobStatus, BadgeVariant> = {
  open: "info",
  processing: "info",
  done: "success",
  partial: "warning",
  failed: "danger",
  cancelled: "neutral",
};

const ITEM_VARIANT: Record<UploadItemStatus, BadgeVariant> = {
  uploaded: "success",
  duplicate: "neutral",
  metadata_updated: "info",
  rejected: "warning",
  infected: "danger",
  failed: "danger",
  discarded: "neutral",
};

export function UploadStatusBadge({ status }: { status: UploadJobStatus }) {
  const t = useTranslations("uploads");
  return <Badge variant={STATUS_VARIANT[status]} dot>{t(`status.${status}`)}</Badge>;
}

export function UploadItemStatusBadge({ status }: { status: UploadItemStatus }) {
  const t = useTranslations("uploads");
  return <Badge variant={ITEM_VARIANT[status]}>{t(`itemStatus.${status}`)}</Badge>;
}

/** «48 hochgeladen · 3 Duplikate · 1 abgelehnt» */
export function resultSummary(job: Pick<UploadJob, "counts">, t: UploadsT): string {
  const { counts } = job;
  const problems = counts.rejected + counts.infected + counts.failed;
  const parts = [
    t("summary.uploaded", { count: counts.uploaded }),
    counts.duplicates ? t("summary.duplicates", { count: counts.duplicates }) : null,
    counts.metadata_updated ? t("summary.metadataUpdated", { count: counts.metadata_updated }) : null,
    problems ? t("summary.problems", { count: problems }) : null,
    counts.discarded ? t("summary.discarded", { count: counts.discarded }) : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

/** Person bzw. «Abgabebox», «Persönlicher Link», «Plattform-Import», «gelöschtes Konto». */
export function actorLabel(job: UploadJob, t: UploadsT): string {
  if (job.actor_kind === "anonymous_link") return t("actor.abgabebox");
  if (job.actor_kind === "submission_person") return t("actor.submissionPerson");
  if (job.actor_kind === "platform_admin") return t("actor.platform");
  if (job.created_by_name) return job.created_by_name;
  return job.created_by_deleted ? t("actor.deleted") : t("actor.unknown");
}

/** Grund eines Items (übersetzt über reason_code, unbekannte Codes neutral). */
export function reasonLabel(code: string | null, t: UploadsT): string | null {
  if (!code) return null;
  const known = [
    "duplicate_exact", "too_large", "unsupported_format", "scan_failed", "infected", "quota_exceeded", "heic_unreadable",
    "rule_violation", "client_rejected", "cancelled",
  ];
  return known.includes(code) ? t(`reason.${code}`) : t("reason.other");
}
