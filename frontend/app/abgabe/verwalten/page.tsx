import { SubmissionAccessPage } from "@/components/submission-access/submission-access-page";
import { ConfirmProvider } from "@/contexts/confirm-context";
import { ToastProvider } from "@/contexts/toast-context";

// Persönlicher Abgabe-Link aus der Mail (#token=…): ohne Login, ohne App-Navigation.
export default function SubmissionAccessRoute() {
  return (
    <ToastProvider>
      <ConfirmProvider>
        <SubmissionAccessPage />
      </ConfirmProvider>
    </ToastProvider>
  );
}
