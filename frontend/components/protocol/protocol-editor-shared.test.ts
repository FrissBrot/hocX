import { describe, expect, it } from "vitest";

import { attendanceParticipants, protocolAttendanceParticipants, tallyAttendance, visibleAttendanceTally } from "./protocol-editor-shared";
import { ParticipantSummary, ProtocolElement, ProtocolElementBlock } from "@/types/api";

function participant(id: string, overrides: Partial<ParticipantSummary> = {}): ParticipantSummary {
  return {
    id,
    tenant_id: "tenant-1",
    first_name: null,
    last_name: null,
    display_name: `Teilnehmer ${id}`,
    email: null,
    is_active: true,
    joined_at: null,
    left_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as ParticipantSummary;
}

function attendanceBlock(overrides: Partial<ProtocolElementBlock> = {}): ProtocolElementBlock {
  return {
    id: "block-1",
    protocol_element_id: "element-1",
    template_element_block_id: null,
    element_definition_id: null,
    element_type_id: 9,
    render_type_id: 1,
    element_type_code: "attendance",
    render_type_code: null,
    title_snapshot: "Anwesenheit",
    display_title_snapshot: null,
    description_snapshot: null,
    block_title_snapshot: null,
    is_editable_snapshot: true,
    allows_multiple_values_snapshot: false,
    sort_index: 10,
    render_order: null,
    is_required_snapshot: false,
    is_visible_snapshot: true,
    export_visible_snapshot: true,
    latex_template_snapshot: null,
    configuration_snapshot_json: {},
    text_content: null,
    display_compiled_text: null,
    display_snapshot_json: null,
    ...overrides,
  } as ProtocolElementBlock;
}

function element(id: string, blocks: ProtocolElementBlock[], overrides: Partial<ProtocolElement> = {}): ProtocolElement {
  return {
    id,
    protocol_id: "protocol-1",
    template_element_id: null,
    sort_index: 10,
    section_name_snapshot: "Abschnitt",
    section_order_snapshot: null,
    is_required_snapshot: false,
    is_visible_snapshot: true,
    export_visible_snapshot: true,
    show_when_empty: true,
    blocks,
    ...overrides,
  } as ProtocolElement;
}

describe("attendanceParticipants / tallyAttendance", () => {
  it("schliesst von der Anwesenheit ausgeschlossene Teilnehmer aus", () => {
    const participants = [participant("1"), participant("2", { exclude_from_attendance: true })];
    expect(attendanceParticipants(participants).map((p) => p.id)).toEqual(["1"]);
  });

  it("zaehlt Status pro teilnahmeberechtigtem Teilnehmer", () => {
    const participants = [participant("1"), participant("2"), participant("3", { exclude_from_attendance: true })];
    const entries = [
      { participant_id: "1", status: "present" },
      { participant_id: "2", status: "excused" },
      { participant_id: "3", status: "present" },
    ];
    expect(tallyAttendance(participants, entries)).toEqual({ present: 1, late: 0, excused: 1, absent: 0 });
  });
});

describe("visibleAttendanceTally", () => {
  it("gibt null zurueck, wenn kein Anwesenheits-Block existiert", () => {
    const participants = [participant("1")];
    const elements = [element("el-1", [attendanceBlock({ element_type_code: "text" })])];
    expect(visibleAttendanceTally(elements, participants)).toBeNull();
  });

  it("ignoriert einen ausgeblendeten Anwesenheits-Block zugunsten des sichtbaren", () => {
    const participants = [participant("1"), participant("2")];
    const hidden = attendanceBlock({
      id: "hidden-block",
      is_visible_snapshot: false,
      sort_index: 1,
      configuration_snapshot_json: { attendance_entries: [{ participant_id: "1", status: "absent" }] },
    });
    const visible = attendanceBlock({
      id: "visible-block",
      sort_index: 2,
      configuration_snapshot_json: {
        attendance_entries: [
          { participant_id: "1", status: "present" },
          { participant_id: "2", status: "present" },
        ],
      },
    });
    const elements = [element("el-1", [hidden, visible])];
    expect(visibleAttendanceTally(elements, participants)).toEqual({ present: 2, late: 0, excused: 0, absent: 0 });
  });

  it("ignoriert einen Anwesenheits-Block in einem ausgeblendeten Element", () => {
    const participants = [participant("1")];
    const hiddenElementBlock = attendanceBlock({
      id: "hidden-element-block",
      sort_index: 1,
      configuration_snapshot_json: { attendance_entries: [{ participant_id: "1", status: "absent" }] },
    });
    const visibleBlock = attendanceBlock({
      id: "visible-block",
      sort_index: 2,
      configuration_snapshot_json: { attendance_entries: [{ participant_id: "1", status: "present" }] },
    });
    const elements = [
      element("hidden-el", [hiddenElementBlock], { is_visible_snapshot: false }),
      element("visible-el", [visibleBlock]),
    ];
    expect(visibleAttendanceTally(elements, participants)).toEqual({ present: 1, late: 0, excused: 0, absent: 0 });
  });

  it("waehlt bei mehreren sichtbaren Anwesenheits-Bloecken den mit dem kleinsten sort_index, unabhaengig von der Array-Reihenfolge", () => {
    const participants = [participant("1")];
    const laterBlock = attendanceBlock({
      id: "later-block",
      sort_index: 20,
      configuration_snapshot_json: { attendance_entries: [{ participant_id: "1", status: "absent" }] },
    });
    const earlierBlock = attendanceBlock({
      id: "earlier-block",
      sort_index: 5,
      configuration_snapshot_json: { attendance_entries: [{ participant_id: "1", status: "present" }] },
    });
    // Array order deliberately reversed vs. sort_index to prove sort_index wins.
    const elements = [element("el-1", [laterBlock, earlierBlock])];
    expect(visibleAttendanceTally(elements, participants)).toEqual({ present: 1, late: 0, excused: 0, absent: 0 });
  });
});


it("behält eingefrorene Anwesenheit auch nach Austritt, Umbenennung und Entfernen aus der Vorlage", () => {
  const entries = [{ participant_id: "old", participant_name: "Damals Mitglied", status: "present" }];
  const current = participant("old", { display_name: "Neuer Name", left_at: "2025-01-01", exclude_from_attendance: true });
  const protocol = { status: "abgeschlossen", protocol_date: "2025-06-01" };
  expect(protocolAttendanceParticipants([current], entries, protocol).map((p) => p.display_name)).toEqual(["Damals Mitglied"]);
  expect(protocolAttendanceParticipants([], entries, protocol).map((p) => p.display_name)).toEqual(["Damals Mitglied"]);
  expect(visibleAttendanceTally([element("el", [attendanceBlock({ configuration_snapshot_json: { attendance_entries: entries } })])], [], "2025-06-01", true))
    .toEqual({ present: 1, late: 0, excused: 0, absent: 0 });
});
