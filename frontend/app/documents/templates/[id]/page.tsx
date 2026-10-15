import { TemplateDesigner } from "@/components/documents/designer/designer";
import { MobileDesktopOnly } from "@/components/mobile/areas/mobile-misc";
import { ResponsiveView } from "@/components/mobile/responsive-view";
import { AppShell } from "@/components/ui/app-shell";
import { requireSession } from "@/lib/api/server";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireSession();
  const { id } = await params;
  return (
    <AppShell initialSession={session}>
      <ResponsiveView mobile={<MobileDesktopOnly navKey="documentStudio" backHref="/documents" backNavKey="documentStudio" />} desktop={<TemplateDesigner templateId={id} />} />
    </AppShell>
  );
}
