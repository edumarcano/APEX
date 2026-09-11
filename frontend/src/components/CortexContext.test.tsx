import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CortexContext } from "./CortexContext";

const record = {
  id: "record-1",
  partition: "production" as const,
  kind: "note" as const,
  text: "Current plan",
  status: "active" as const,
  subject: null,
  predicate: null,
  object_entity: null,
  object_value: null,
  effective_at: null,
  supersedes_record_id: null,
  created_at: "2026-09-10T10:00:00Z",
  updated_at: "2026-09-10T11:00:00Z",
};
const detail = {
  ...record,
  sources: [
    {
      id: "source-1",
      kind: "manual" as const,
      origin: "operator_input" as const,
      locator: "manual",
      original_text: "I said keep it concise.",
      occurred_at: "2026-09-10T09:00:00Z",
      captured_at: "2026-09-10T10:00:00Z",
      created_at: "2026-09-10T10:00:00Z",
      derivation: "direct" as const,
      linked_at: "2026-09-10T10:00:00Z",
    },
  ],
  predecessors: ["older-record"],
  superseded_by: [],
  related_records: [],
  history: [
    {
      id: "history-1",
      record_id: record.id,
      operation: "created",
      actor: "operator",
      reason_code: "manual_save",
      related_record_id: null,
      source_id: "source-1",
      action_id: null,
      review_id: null,
      created_at: "2026-09-10T10:00:00Z",
    },
  ],
  pending_review_ids: [],
};
const review = {
  id: "review-1",
  partition: "production" as const,
  operation: "correct",
  proposal: { capture: { text: "Proposed replacement" } },
  evidence: { original_text: "New evidence" },
  expected_revisions: { [record.id]: record.updated_at },
  reason_codes: ["known_conflict"],
  decision: "pending" as const,
  action_id: "action-42",
  decision_at: null,
  created_at: "2026-09-10T12:00:00Z",
};

function inspectorFixture(overrides: Record<string, unknown> = {}) {
  return {
    records: [record],
    detail,
    selectedRecordId: record.id,
    filters: { query: "", kind: "", statuses: ["active"] },
    setFilters: vi.fn(),
    retrieval: {
      enabled: true,
      mode: "fts_only",
      state: "unprepared",
      indexed_items: 1,
      embedding_items: 0,
      pending_items: 1,
      last_prepared_at: null,
      error_category: null,
      model_fingerprint: null,
    },
    isLoading: false,
    isDetailLoading: false,
    isPreparing: false,
    error: null,
    entities: [],
    lastCreatedRecordId: null,
    reviews: [review],
    pendingReviewCount: 1,
    reviewFilters: { decisions: ["pending"] },
    setReviewFilters: vi.fn(),
    selectedReviewId: review.id,
    reviewDetail: review,
    reviewRecords: [detail],
    isReviewLoading: false,
    reviewMutation: null,
    reviewRefreshRequired: false,
    refresh: vi.fn(),
    selectRecord: vi.fn(),
    selectReview: vi.fn(),
    decideReview: vi.fn(),
    prepare: vi.fn(),
    searchEntities: vi.fn(),
    save: vi.fn().mockResolvedValue({ outcome: "saved" }),
    capture: vi.fn(),
    reconcile: vi.fn(),
    rememberVerifiedRecord: vi.fn(),
    ...overrides,
  } as unknown as Parameters<typeof CortexContext>[0]['inspector'];
}

describe("CortexContext", () => {
  it("renders source history and navigates related records", () => {
    const inspector = inspectorFixture();
    render(
      <CortexContext
        inspector={inspector}
        demoModeActive={false}
        onOpenActions={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Original evidence"));
    expect(screen.getByText("I said keep it concise.")).toBeInTheDocument();
    expect(
      screen.getByText(/2026-09-10T10:00:00Z · created/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Open related record"));
    expect(inspector.selectRecord).toHaveBeenCalledWith("older-record");
  });

  it("saves direct entries and distinguishes review-required results", async () => {
    const inspector = inspectorFixture({
      detail: null,
      save: vi
        .fn()
        .mockResolvedValueOnce({ outcome: "saved" })
        .mockResolvedValueOnce({ outcome: "review_required" }),
    });
    render(
      <CortexContext
        inspector={inspector}
        demoModeActive={false}
        onOpenActions={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Capture"));
    fireEvent.change(screen.getByLabelText("Manual context text"), {
      target: { value: "  first  " },
    });
    fireEvent.click(screen.getByText("Save context"));
    expect(await screen.findByText(/Saved. This is now/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Manual context text"), {
      target: { value: "second" },
    });
    fireEvent.click(screen.getByText("Save context"));
    expect(await screen.findByText(/Needs review/)).toBeInTheDocument();
    expect(inspector.save).toHaveBeenCalledWith(
      expect.objectContaining({ text: "first" }),
    );
  });

  it("supports keyboard tab navigation and keeps proposals separate from current records", () => {
    const onOpenActions = vi.fn();
    render(
      <CortexContext
        inspector={inspectorFixture()}
        demoModeActive={false}
        onOpenActions={onOpenActions}
      />,
    );
    fireEvent.keyDown(screen.getByRole("tab", { name: /Records/ }), {
      key: "ArrowRight",
    });
    expect(
      screen.getByRole("tabpanel", { name: /Review/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/note · active · Not recorded · Current plan/)).toBeInTheDocument();
    expect(screen.getByText("Proposed replacement")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Open linked action"));
    expect(onOpenActions).toHaveBeenCalledWith("action-42");
  });

  it("opens a record's pending review and selects its exact id", () => {
    const inspector = inspectorFixture({
      detail: { ...detail, pending_review_ids: ["review-pending"] },
    });
    render(
      <CortexContext
        inspector={inspector}
        demoModeActive={false}
        onOpenActions={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Open review review-pending" }));

    expect(inspector.selectReview).toHaveBeenCalledWith("review-pending");
    expect(screen.getByRole("tab", { name: /Review/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tabpanel", { name: /Review/ })).toBeInTheDocument();
  });

  it("keeps one review decision selected and displays review context", () => {
    const setReviewFilters = vi.fn();
    render(
      <CortexContext
        inspector={inspectorFixture({ setReviewFilters })}
        demoModeActive={false}
        onOpenActions={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: /Review/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "pending" }));

    const update = setReviewFilters.mock.calls[0][0] as (current: { decisions: string[] }) => unknown;
    expect(update({ decisions: ["pending"] })).toEqual({ decisions: ["pending"] });
    expect(screen.getByText(/correct · 2026-09-10T12:00:00Z/)).toBeInTheDocument();
    expect(screen.getAllByText(/known conflict/)).toHaveLength(2);
    expect(screen.getByText(/note · active · Not recorded · Current plan/)).toBeInTheDocument();
  });

  it("uses the selected record kind for corrections and clears correction state on navigation", async () => {
    const save = vi.fn().mockResolvedValue({ outcome: "saved" });
    const first = { ...detail, id: "record-a", kind: "note" as const };
    const second = { ...detail, id: "record-b", kind: "decision" as const };
    const { rerender } = render(
      <CortexContext
        inspector={inspectorFixture({ detail: first })}
        demoModeActive={false}
        onOpenActions={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    expect(screen.getByLabelText("Correction kind")).toHaveValue("note");

    rerender(
      <CortexContext
        inspector={inspectorFixture({ detail: second, save })}
        demoModeActive={false}
        onOpenActions={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("Correction text")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    fireEvent.change(screen.getByLabelText("Correction text"), {
      target: { value: "Decide differently" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save context" }));
    expect(await screen.findByText(/Saved. This is now/)).toBeInTheDocument();
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "decision",
        correction_record_id: "record-b",
      }),
    );
  });

  it("disables writes in demo mode and shows representative empty states", () => {
    const entityDetail = {
      ...detail,
      subject: { id: "entity-1", name: "Apex", aliases: [] },
    };
    render(
      <CortexContext
        inspector={inspectorFixture({
          records: [],
          detail: entityDetail,
          reviews: [],
          reviewDetail: null,
        })}
        demoModeActive
        onOpenActions={vi.fn()}
      />,
    );
    expect(screen.getByText("Capture")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Correct" }));
    expect(screen.getByLabelText("Add entity alias")).toBeDisabled();
    expect(screen.getByLabelText("Merge entity into")).toBeDisabled();
    fireEvent.click(screen.getByText("Capture"));
    expect(screen.queryByLabelText("Manual context text")).not.toBeInTheDocument();
    expect(screen.getByText(/No context records/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Review/ }));
    expect(screen.getByText(/No reviews match/)).toBeInTheDocument();
  });
});
