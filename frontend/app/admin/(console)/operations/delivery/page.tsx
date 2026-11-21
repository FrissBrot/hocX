import { AdminEmailLog } from "@/components/admin/admin-email-log";

// Betrieb › Zustellung: E-Mail-Versandprotokoll (früher Teil von /admin/notifications).
export default function AdminDeliveryPage() {
  return (
    <section className="panel">
      <AdminEmailLog />
    </section>
  );
}
