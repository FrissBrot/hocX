import { redirect } from "next/navigation";

// The tools index only ever listed one entry; the sidebar links straight to the import queue.
export default function ToolsPage() {
  redirect("/tools/import");
}
