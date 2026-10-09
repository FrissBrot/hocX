import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));

import { attendanceFineConfig, syncAttendanceFine } from "@/components/protocol/attendance-fines";
import type { AttendanceFine } from "@/types/api";

const participant = { id: "p1", display_name: "Dario Huber" };
const config = attendanceFineConfig({ fine_account_id: "acc", fine_amount_late: 5, fine_amount_absent: 20 });

function fine(type: "late" | "absent"): AttendanceFine {
  return {
    id: `f-${type}`, protocol_id: "pr", participant_id: "p1", participant_name_snapshot: "Dario Huber", fine_type: type,
    amount: type === "late" ? 5 : 20, account_id: "acc", status: "pending", collected_at: null, collected_transaction_id: null,
    closed_in_protocol_id: null, collected_by_user_id: null, collected_by_display_name: null, can_reopen: false, created_at: "",
  };
}

describe("attendance-fines", () => {
  beforeEach(() => api.mockReset());

  it("ist ohne Konto oder Betraege deaktiviert", () => {
    expect(attendanceFineConfig({ fine_amount_absent: 20 }).enabled).toBe(false);
    expect(attendanceFineConfig({ fine_account_id: "acc" }).enabled).toBe(false);
    expect(config.enabled).toBe(true);
  });

  it("legt fuer Unentschuldigt die Busse an", async () => {
    api.mockResolvedValueOnce(fine("absent"));
    const onCreated = vi.fn();
    await syncAttendanceFine({ protocolId: "pr", participant, status: "absent", config, fines: [], onRemoved: vi.fn(), onCreated });
    expect(api).toHaveBeenCalledWith("/api/fines", expect.objectContaining({ method: "POST" }));
    expect(JSON.parse(api.mock.calls[0][1].body)).toMatchObject({ fine_type: "absent", amount: 20, account_id: "acc" });
    expect(onCreated).toHaveBeenCalledWith(fine("absent"));
  });

  it("ersetzt eine andersartige offene Busse", async () => {
    api.mockResolvedValueOnce(undefined).mockResolvedValueOnce(fine("late"));
    const onRemoved = vi.fn();
    await syncAttendanceFine({ protocolId: "pr", participant, status: "late", config, fines: [fine("absent")], onRemoved, onCreated: vi.fn() });
    expect(api.mock.calls[0]).toEqual(["/api/fines/f-absent", { method: "DELETE" }]);
    expect(onRemoved).toHaveBeenCalledWith("f-absent");
  });

  it("laesst eine passende Busse unveraendert", async () => {
    await syncAttendanceFine({ protocolId: "pr", participant, status: "late", config, fines: [fine("late")], onRemoved: vi.fn(), onCreated: vi.fn() });
    expect(api).not.toHaveBeenCalled();
  });

  it("entfernt die Busse bei Anwesend", async () => {
    api.mockResolvedValueOnce(undefined);
    const onRemoved = vi.fn();
    await syncAttendanceFine({ protocolId: "pr", participant, status: "present", config, fines: [fine("late")], onRemoved, onCreated: vi.fn() });
    expect(onRemoved).toHaveBeenCalledWith("f-late");
  });
});
