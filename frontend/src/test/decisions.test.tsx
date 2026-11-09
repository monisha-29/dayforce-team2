import { describe, expect, it } from "vitest";
import { api } from "@/lib/api/client";

describe("manager decision rules (mock backend)", () => {
  it("refuses to approve a proposal blocked by failed validation", async () => {
    // PRP-7102 (EXC-2402, Overtime Risk) has a failing Working Hours Validation (blocked: true).
    // Approval must be rejected unless the proposal is edited and revalidated.
    await expect(api.submitDecision("PRP-7102", { decision: "approve" })).rejects.toThrow(
      /blocked/,
    );
  });

  it("requires a reason to reject", async () => {
    // PRP-7101 (EXC-2401, Missing Punch) is Awaiting Approval.
    // Rejection requires a non-empty, non-whitespace explanation.
    await expect(
      api.submitDecision("PRP-7101", { decision: "reject", reason: " " }),
    ).rejects.toThrow(/reason/);
  });

  it("rejects edited timecards over 16 hours", async () => {
    // PRP-7101 edited timecard 01:00 -> 23:00 spans 22 hours, exceeding the 16-hour cap.
    await expect(
      api.submitDecision("PRP-7101", {
        decision: "edit",
        editedTimecard: {
          checkIn: "01:00",
          checkOut: "23:00",
          mealStart: null,
          mealEnd: null,
          totalHours: null,
        },
      }),
    ).rejects.toThrow(/16/);
  });
});
