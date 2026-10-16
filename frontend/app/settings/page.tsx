import { redirect } from "next/navigation";

// Die früheren Hausstil-Einstellungen sind im Brand Studio des Document Studio aufgegangen.
export default function SettingsPage() {
  redirect("/documents/brand");
}
