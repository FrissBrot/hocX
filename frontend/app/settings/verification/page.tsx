import { redirect } from "next/navigation";

// Die Echtheitsprüfung ist in die Mandanten-Einstellungen umgezogen.
export default function DocumentVerificationPage() {
  redirect("/tenant-settings/verification");
}
