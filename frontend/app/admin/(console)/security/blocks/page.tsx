import { SecurityBlocks } from "@/components/admin/security/security-blocks";
import { adminIsOwner } from "@/lib/admin/tenant-detail-server";

export default async function AdminSecurityBlocksPage() {
  const isOwner = await adminIsOwner();
  return (
    <section className="panel section-stack admin-security-panel">
      <SecurityBlocks canWrite={isOwner} />
    </section>
  );
}
