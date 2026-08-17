import { notFound } from "next/navigation";
import Link from "next/link";

import { UploadForm } from "@/components/upload-form";
import { getAssignmentDetail, getElement } from "@/lib/api";

export default async function ElementUploadPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; assignmentSlug: string; elementRef: string }>;
}) {
  const { tenantSlug, assignmentSlug, elementRef } = await params;
  const [assignment, element] = await Promise.all([
    getAssignmentDetail(tenantSlug, assignmentSlug),
    getElement(tenantSlug, assignmentSlug, elementRef),
  ]);

  if (assignment === null || element === null) {
    notFound();
  }

  const sitekey = process.env.NEXT_PUBLIC_FRIENDLY_CAPTCHA_SITEKEY ?? "";

  return (
    <div>
      <h1>{element.label}</h1>
      <p className="muted">{assignment.title}</p>

      <UploadForm
        tenantSlug={tenantSlug}
        assignmentSlug={assignmentSlug}
        elementRef={elementRef}
        allowedFileTypes={assignment.allowed_file_types}
        maxFiles={assignment.max_files_per_element}
        maxFileSizeMb={assignment.max_file_size_mb}
        alreadyUploadedCount={element.uploaded_count}
        sitekey={sitekey}
      />

      <Link href={`/${tenantSlug}/${assignmentSlug}`} className="back-btn">
        ← Zurück zur Übersicht
      </Link>
    </div>
  );
}
