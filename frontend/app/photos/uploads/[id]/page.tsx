import { UploadJobPage } from "@/components/uploads/upload-pages";

export default async function PhotoUploadJobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <UploadJobPage area="photos" id={id} />;
}
