import { describe, expect, it } from "vitest";
import { api } from "@/lib/api/client";

describe("manager decision rules (mock backend)", () => {
  it("refuses to approve a proposal blocked by failed validation", async () => {
    // EXC-2402 has a failing Working Hours Validation
    await expect(api.submitDecision("PRP-7102", { decision: "approve" })).rejects.toThrow(/blocked/);
  });
  it("requires a reason to reject", async () => {
    await expect(api.submitDecision("PRP-7101", { decision: "reject", reason: " " })).rejects.toThrow(/reason/);
  });
  it("rejects edited timecards over 16 hours", async () => {
    await expect(
      api.submitDecision("PRP-7101", { decision: "edit", editedTimecard: { checkIn: "01:00", checkOut: "23:00", mealStart: null, mealEnd: null, totalHours: null } }),
    ).rejects.toThrow(/16/);
  });
});
