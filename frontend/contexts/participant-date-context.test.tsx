import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ParticipantDateContext, useParticipantSelectable } from "./participant-date-context";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";

const participants = [
  { id: "departed", display_name: "Früheres Mitglied", joined_at: "2020-01-01", left_at: "2026-08-15" },
  { id: "current", display_name: "Aktuelles Mitglied", joined_at: null, left_at: null },
  { id: "future", display_name: "Künftiges Mitglied", joined_at: "2027-01-01", left_at: null },
];

function Picker({ multi = false }: { multi?: boolean }) {
  const isSelectable = useParticipantSelectable();
  const shared = { options: participants, getId: (p: typeof participants[number]) => p.id,
    getLabel: (p: typeof participants[number]) => p.display_name, isOptionSelectable: isSelectable };
  return multi
    ? <SearchableMultiSelect {...shared} values={["departed"]} onChange={vi.fn()} />
    : <SearchableSelect {...shared} value="departed" onChange={vi.fn()} />;
}

afterEach(() => vi.useRealTimers());

describe("Teilnehmerauswahl nach Bezugsdatum", () => {
  it.each([false, true])("behält alte Labels, bietet aber nach Austritt keine Auswahl (multi=%s)", (multi) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 4, 12));
    render(<Picker multi={multi} />);
    fireEvent.click(screen.getByRole("button", { name: /Früheres Mitglied/ }));
    const list = within(screen.getByRole("listbox"));
    expect(list.queryByText("Früheres Mitglied")).not.toBeInTheDocument();
    expect(list.getByText("Aktuelles Mitglied")).toBeInTheDocument();
    expect(list.queryByText("Künftiges Mitglied")).not.toBeInTheDocument();
  });

  it("verwendet das historische Protokolldatum einschließlich Austrittstag", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 9, 4, 12));
    render(<ParticipantDateContext.Provider value="2026-08-15"><Picker /></ParticipantDateContext.Provider>);
    fireEvent.click(screen.getByRole("button", { name: /Früheres Mitglied/ }));
    expect(within(screen.getByRole("listbox")).getByText("Früheres Mitglied")).toBeInTheDocument();
  });

  it("filtert auch Aufgaben-Zuweisungen nach dem Protokolldatum", () => {
    render(<ParticipantDateContext.Provider value="2026-08-16">
      <TodoAssigneeMenu participants={participants} activeId="departed" label="Früheres Mitglied" onChange={vi.fn()} />
    </ParticipantDateContext.Provider>);
    fireEvent.click(screen.getByRole("button", { name: /Früheres Mitglied/ }));
    expect(within(screen.getByRole("listbox")).queryByText("Früheres Mitglied")).not.toBeInTheDocument();
    expect(within(screen.getByRole("listbox")).getByText("Aktuelles Mitglied")).toBeInTheDocument();
  });
});
