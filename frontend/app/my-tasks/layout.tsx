import { AreaIntlProvider } from "@/components/i18n/area-intl-provider";
import "@/app/styles/todos.css";

// Dieselbe Ansicht wie /todos (TodoListView personal): gleiche Styles und Namespaces.
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <AreaIntlProvider area="myTasks">{children}</AreaIntlProvider>;
}
