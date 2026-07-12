import { notFound } from "next/navigation";
import Link from "next/link";

import { UploadForm } from "@/components/upload-form";
import { getAssignmentDetail, getElement } from "@/lib/api";

export default async function ElementUploadPage({
  params,
}: {
  params: { tenantSlug: string; assignmentSlug: string; elementRef: string };
}) {
  const [assignment, element] = await Promise.all([
    getAssignmentDetail(params.tenantSlug, params.assignmentSlug),
    getElement(params.tenantSlug, params.assignmentSlug, params.elementRef),
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
        tenantSlug={params.tenantSlug}
        assignmentSlug={params.assignmentSlug}
        elementRef={params.elementRef}
        allowedFileTypes={assignment.allowed_file_types}
        maxFiles={assignment.max_files_per_element}
        maxFileSizeMb={assignment.max_file_size_mb}
        sitekey={sitekey}
      />

      <Link href={`/${params.tenantSlug}/${params.assignmentSlug}`} className="back-btn">
        ← Zurück zur Übersicht
      </Link>
    </div>
  );
}
