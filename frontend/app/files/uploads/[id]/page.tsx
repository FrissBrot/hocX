import { UploadJobPage } from "@/components/uploads/upload-pages";

export default async function FileUploadJobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <UploadJobPage area="files" id={id} />;
}
