import { notFound } from "next/navigation";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { UploadForm } from "@/components/upload-form";
import { getAssignmentDetail, getElement } from "@/lib/api";
import { resolvePuzzleEndpoint } from "@/lib/friendly-captcha";
import { formatDate } from "@/lib/format";

export default async function ElementUploadPage({
  params,
}: {
  params: Promise<{ linkToken: string; assignmentSlug: string; elementRef: string }>;
}) {
  const { linkToken, assignmentSlug, elementRef } = await params;
  const [assignment, element] = await Promise.all([
    getAssignmentDetail(linkToken, assignmentSlug),
    getElement(linkToken, assignmentSlug, elementRef),
  ]);

  if (assignment === null || element === null) {
    notFound();
  }

  const sitekey = process.env.NEXT_PUBLIC_FRIENDLY_CAPTCHA_SITEKEY ?? "";
  const puzzleEndpoint = resolvePuzzleEndpoint(process.env.FRIENDLY_CAPTCHA_PUZZLE_URL);
  const t = await getTranslations("abgabebox.elements");
  const windowText = element.window_start && element.window_end
    ? `${formatDate(element.window_start)} – ${formatDate(element.window_end)}`
    : element.window_start
      ? t("windowFrom", { date: formatDate(element.window_start) })
      : element.window_end
        ? t("windowUntil", { date: formatDate(element.window_end) })
        : null;

  return (
    <div className="box-step">
      <div className="box-step-head">
        <Link href={`/${linkToken}/${assignmentSlug}`} className="back-link">
          {t("backTo", { title: assignment.title })}
        </Link>
        <h1>{element.label}</h1>
        <p className="muted">{windowText ?? assignment.title}</p>
      </div>

      <UploadForm
        linkToken={linkToken}
        assignmentSlug={assignmentSlug}
        elementRef={elementRef}
        assignmentTitle={assignment.title}
        elementLabel={element.label}
        allowedFileTypes={assignment.allowed_file_types}
        maxFiles={assignment.max_files_per_element}
        maxFileSizeMb={assignment.max_file_size_mb}
        alreadyUploadedCount={element.uploaded_count}
        sitekey={sitekey}
        puzzleEndpoint={puzzleEndpoint}
        tenantName={assignment.tenant_name}
        privacyNoticeUrl={assignment.privacy_notice_url}
      />
    </div>
  );
}
