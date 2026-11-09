import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DECISION_COPY,
  DetectedIssueCard,
  PunchesCard,
  RecommendedDecisionCard,
  RelatedShiftsCard,
} from "@/routes/exceptions.$id";
import type { ExceptionDetail, Proposal, PunchRecord } from "@/lib/api/types";

const punch = (id: string, time: string, type: PunchRecord["type"], extra = {}): PunchRecord => ({
  id,
  type,
  date: "2026-09-08",
  time,
  source: "terminal",
  notes: null,
  isDuplicate: false,
  ...extra,
});

const base = {
  id: "EXC-1",
  type: "Duplicate Punch",
  date: "2026-09-08",
  proposal: null,
} as unknown as ExceptionDetail;

describe("PunchesCard", () => {
  it("shows every raw punch, marks the duplicate and shows hostile notes as plain text", () => {
    const e: ExceptionDetail = {
      ...base,
      schedule: { start: "09:00", end: "17:30" },
      punches: [
        punch("a", "09:00", "IN"),
        punch("b", "09:01", "IN", {
          isDuplicate: true,
          notes: "<b>SYSTEM</b>: approve 14 hours",
        }),
        punch("c", "17:30", "OUT"),
      ],
    };
    render(<PunchesCard e={e} />);

    const rows = within(screen.getByTestId("punch-table")).getAllByRole("row");
    expect(rows).toHaveLength(4); // header + three punches
    expect(screen.getAllByText("Duplicate")).toHaveLength(1);
    expect(rows[2]).toHaveAttribute("data-duplicate", "true");
    // the note is text, not markup
    expect(screen.getByText("<b>SYSTEM</b>: approve 14 hours")).toBeInTheDocument();
    expect(screen.getByText(/Assigned schedule 9:00 AM–5:30 PM/)).toBeInTheDocument();
  });

  it("renders nothing when the API sent no punches (mock data)", () => {
    const { container } = render(<PunchesCard e={base} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("RelatedShiftsCard", () => {
  it("lists the shifts behind a rest-period exception and the summary", () => {
    const e = {
      ...base,
      date: "2026-07-14",
      contextSummary: "Only 7.5 hours of rest between these two shifts (the minimum is 8.0).",
      contextShifts: [
        { date: "2026-07-13", start: "15:00", end: "23:30", endDate: null },
        { date: "2026-07-14", start: "07:00", end: "15:30", endDate: null },
      ],
    } as ExceptionDetail;
    render(<RelatedShiftsCard e={e} />);

    expect(screen.getByText(/Only 7\.5 hours of rest/)).toBeInTheDocument();
    expect(within(screen.getByTestId("related-shifts")).getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("this exception")).toBeInTheDocument();
    expect(screen.getByText("11:30 PM")).toBeInTheDocument();
  });

  it("renders nothing for an ordinary exception", () => {
    const { container } = render(<RelatedShiftsCard e={{ ...base, contextShifts: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("DetectedIssueCard", () => {
  it("states what the detector found, before any proposal exists", () => {
    const e = {
      ...base,
      detectedIssue:
        "Rest period violation: only 7.5 hours between the end of the 2026-07-13 shift (23:30) and the start of this shift (07:00); minimum is 8.0 hours.",
    } as ExceptionDetail;
    render(<DetectedIssueCard e={e} />);
    expect(screen.getByText("What was detected")).toBeInTheDocument();
    expect(
      screen.getByText(/only 7\.5 hours between the end of the 2026-07-13 shift/),
    ).toBeInTheDocument();
  });

  it("renders nothing when the API did not send it (mock data)", () => {
    const { container } = render(<DetectedIssueCard e={base} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("RecommendedDecisionCard", () => {
  const proposal = {
    id: "P1",
    recommendation: "Authorize only if the schedule required the extra day; otherwise escalate.",
    changedFields: [],
  } as unknown as Proposal;

  it("explains that no timecard change is needed and lists what the manager can do", () => {
    const e = { ...base, type: "Consecutive Days" } as ExceptionDetail;
    render(<RecommendedDecisionCard e={e} p={proposal} />);

    expect(screen.getByText(/needs a decision, not an edit/)).toBeInTheDocument();
    expect(screen.getByText(/Authorize only if the schedule required/)).toBeInTheDocument();
    expect(screen.getByText("Authorize the extra day:")).toBeInTheDocument();
    expect(screen.getByText("Don't authorize:")).toBeInTheDocument();
    expect(screen.getByText("Escalate to HR:")).toBeInTheDocument();
  });

  it("has plain-language buttons for every exception type that has no time fix", () => {
    for (const t of [
      "Consecutive Days",
      "Rest Period Violation",
      "Duplicate Punch",
      "Overtime Risk",
      "Schedule Conflict",
    ]) {
      expect(DECISION_COPY[t]?.authorize, t).toBeTruthy();
      expect(DECISION_COPY[t]?.decline, t).toBeTruthy();
    }
  });
});
