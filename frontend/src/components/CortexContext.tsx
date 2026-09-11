import { Loader2 } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";

import type { useContextInspector } from "../hooks/useContextInspector";
import type {
  ContextCaptureInput,
  ContextKind,
  ContextRecord,
  ContextReview,
} from "../types/context";

type Inspector = ReturnType<typeof useContextInspector>;
type View = "records" | "review";
const KINDS: ContextKind[] = [
  "idea",
  "preference",
  "decision",
  "goal",
  "fact",
  "constraint",
  "note",
  "observation",
];
const STATUSES = ["active", "conflicting", "superseded", "retracted"] as const;
const REVIEW_DECISIONS = ["pending", "accepted", "rejected", "stale"] as const;

function statusClass(status: string): string {
  if (status === "active" || status === "accepted") return "text-emerald-200";
  if (status === "conflicting" || status === "pending") return "text-amber-200";
  if (status === "retracted") return "text-red-200";
  return "text-zinc-500";
}
function display(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "Not recorded";
}
function proposalSummary(review: ContextReview): string {
  const capture = review.proposal.capture;
  const nestedText =
    capture && typeof capture === "object" && !Array.isArray(capture)
      ? (capture as Record<string, unknown>).text
      : null;
  const captureText =
    typeof nestedText === "string" && nestedText.trim()
      ? nestedText
      : review.proposal.text;
  if (review.operation === "capture" || review.operation === "correct") {
    return display(captureText);
  }
  if (review.operation === "retract") return `Retract record ${display(review.proposal.record_id)}`;
  if (review.operation === "restore") return `Restore record ${display(review.proposal.record_id)}`;
  if (review.operation === "set_current") return `Set current record ${display(review.proposal.record_id)}`;
  if (review.operation === "add_alias") return `Add alias ${display(review.proposal.alias)} to entity ${display(review.proposal.entity_id)}`;
  if (review.operation === "merge_entities") return `Merge entity ${display(review.proposal.source_entity_id)} into ${display(review.proposal.target_entity_id)}`;
  return `${review.operation.replaceAll("_", " ")} proposal`;
}
function proposalEvidence(review: ContextReview): string {
  const originalText = review.evidence.original_text;
  return typeof originalText === "string" && originalText.trim()
    ? `Proposal evidence: ${originalText}`
    : "No proposal evidence recorded";
}

function SaveForm({
  label,
  disabled,
  initialKind = "note",
  onSave,
}: {
  label: string;
  disabled: boolean;
  initialKind?: ContextKind;
  onSave: (
    input: ContextCaptureInput,
  ) => Promise<"saved" | "review_required" | null>;
}): ReactElement {
  const [kind, setKind] = useState<ContextKind>(initialKind);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<"saved" | "review_required" | null>(
    null,
  );
  const submit = async (): Promise<void> => {
    if (!text.trim() || saving) return;
    setSaving(true);
    setOutcome(null);
    const result = await onSave({ kind, text: text.trim() });
    setOutcome(result);
    if (result) setText("");
    setSaving(false);
  };
  return (
    <div className="space-y-2 rounded-lg border border-white/10 bg-white/[0.02] p-3">
      <p className="font-mono text-[10px] uppercase text-zinc-500">{label}</p>
      <select
        aria-label={`${label} kind`}
        value={kind}
        disabled={disabled || saving}
        onChange={(event) => setKind(event.target.value as ContextKind)}
        className="w-full rounded border border-white/10 bg-zinc-950 p-2 text-xs"
      >
        {KINDS.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
      <textarea
        aria-label={`${label} text`}
        value={text}
        disabled={disabled || saving}
        onChange={(event) => setText(event.target.value)}
        maxLength={10000}
        rows={3}
        className="w-full rounded border border-white/10 bg-zinc-950 p-2 text-xs"
      />
      <button
        type="button"
        disabled={disabled || saving || !text.trim()}
        onClick={() => void submit()}
        className="text-xs text-[#7EB3FF] disabled:opacity-45"
      >
        {saving ? "Saving…" : "Save context"}
      </button>
      {outcome === "saved" ? (
        <p role="status" className="text-xs text-emerald-200">
          Saved. This is now current context.
        </p>
      ) : null}
      {outcome === "review_required" ? (
        <p role="status" className="text-xs text-amber-200">
          Needs review. The proposed information is not current context.
        </p>
      ) : null}
    </div>
  );
}
function RecordRow({
  record,
  selected,
  onSelect,
}: {
  record: ContextRecord;
  selected: boolean;
  onSelect: () => void;
}): ReactElement {
  return (
    <button
      type="button"
      aria-expanded={selected}
      onClick={onSelect}
      className="w-full rounded-lg border border-white/10 p-2 text-left"
    >
      <span
        className={`font-mono text-[10px] uppercase ${statusClass(record.status)}`}
      >
        {record.status}
      </span>
      <span className="ml-2 text-xs text-zinc-200">{record.text}</span>
    </button>
  );
}

function RecordDetail({
  inspector,
  demoModeActive,
  onOpenReview,
  onSave,
}: {
  inspector: Inspector;
  demoModeActive: boolean;
  onOpenReview: (reviewId: string) => void;
  onSave: (
    input: ContextCaptureInput,
    correction?: boolean,
  ) => Promise<"saved" | "review_required" | null>;
}): ReactElement | null {
  const [showCorrection, setShowCorrection] = useState(false);
  const [alias, setAlias] = useState("");
  const [target, setTarget] = useState("");
  const detail = inspector.detail;
  if (!detail) return null;
  const entity = detail.subject ?? detail.object_entity;
  const relatedIds = [
    ...new Set([
      ...detail.predecessors,
      ...detail.superseded_by,
      ...detail.related_records.map((record) => record.id),
    ]),
  ];
  const reconcile = async (
    operation: Parameters<Inspector["reconcile"]>[0],
  ): Promise<void> => {
    if (await inspector.reconcile(operation)) await inspector.refresh();
  };
  return (
    <div className="space-y-3 rounded-lg border border-white/10 bg-black/20 p-3">
      <div>
        <p className="font-mono text-[10px] uppercase text-zinc-500">
          Current normalized record
        </p>
        <p className="text-xs text-zinc-100">{detail.text}</p>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-[11px] text-zinc-400">
        <div>
          <dt>Subject</dt>
          <dd>{detail.subject?.name ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Predicate</dt>
          <dd>{detail.predicate ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Object</dt>
          <dd>
            {detail.object_entity?.name ??
              detail.object_value ??
              "Not recorded"}
          </dd>
        </div>
        <div>
          <dt>Aliases</dt>
          <dd>{entity?.aliases.join(", ") || "None"}</dd>
        </div>
        <div>
          <dt>Effective</dt>
          <dd>{detail.effective_at ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Captured</dt>
          <dd>{detail.created_at}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{detail.updated_at}</dd>
        </div>
      </dl>
      <details>
        <summary className="cursor-pointer text-xs text-[#7EB3FF]">
          Original evidence
        </summary>
        {detail.sources.length ? (
          <div className="mt-2 space-y-2">
            {detail.sources.map((source) => (
              <div key={source.id} className="text-[11px] text-zinc-400">
                <p className="text-zinc-200">{source.original_text}</p>
                <p>
                  Origin: {source.origin} · Derivation: {source.derivation}
                </p>
                <p>
                  Locator: {source.locator} · Occurred:{" "}
                  {source.occurred_at ?? "Not recorded"} · Captured:{" "}
                  {source.captured_at}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-xs text-zinc-500">
            No source evidence is available.
          </p>
        )}
      </details>
      <div>
        <p className="font-mono text-[10px] uppercase text-zinc-500">History</p>
        {detail.history.length ? (
          <ol className="space-y-1">
            {detail.history.map((event) => (
              <li key={event.id} className="text-[11px] text-zinc-400">
                {event.created_at} · {event.operation} · {event.reason_code}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs text-zinc-500">No recorded history yet.</p>
        )}
      </div>
      {detail.pending_review_ids.length ? (
        <div>
          {detail.pending_review_ids.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => onOpenReview(id)}
              className="mr-2 text-xs text-[#7EB3FF]"
            >
              Open review {id}
            </button>
          ))}
        </div>
      ) : null}
      {relatedIds.length ? (
        <div>
          <p className="font-mono text-[10px] uppercase text-zinc-500">
            Related records
          </p>
          {relatedIds.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => void inspector.selectRecord(id)}
              className="mr-2 text-xs text-[#7EB3FF]"
            >
              Open related record
            </button>
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2 text-xs">
        {detail.status === "active" ? (
          <button
            type="button"
            disabled={demoModeActive}
            onClick={() => setShowCorrection((current) => !current)}
            className="text-[#7EB3FF] disabled:opacity-45"
          >
            Correct
          </button>
        ) : null}
        {detail.status === "conflicting" ? (
          <button
            type="button"
            disabled={demoModeActive}
            onClick={() =>
              void reconcile({ operation: "set_current", record_id: detail.id })
            }
            className="text-[#7EB3FF] disabled:opacity-45"
          >
            Set current
          </button>
        ) : null}
        {["active", "conflicting"].includes(detail.status) ? (
          <button
            type="button"
            disabled={demoModeActive}
            onClick={() =>
              void reconcile({ operation: "retract", record_id: detail.id })
            }
            className="text-red-200 disabled:opacity-45"
          >
            Retract
          </button>
        ) : null}
        {detail.status === "retracted" ? (
          <button
            type="button"
            disabled={demoModeActive}
            onClick={() =>
              void reconcile({ operation: "restore", record_id: detail.id })
            }
            className="text-[#7EB3FF] disabled:opacity-45"
          >
            Restore
          </button>
        ) : null}
      </div>
      {showCorrection ? (
        <SaveForm
          label="Correction"
          disabled={demoModeActive}
          initialKind={detail.kind}
          onSave={(input) => onSave(input, true)}
        />
      ) : null}
      {entity ? (
        <div className="space-y-2 border-t border-white/10 pt-2">
          <p className="text-xs text-zinc-300">Entity: {entity.name}</p>
          <input
            aria-label="Add entity alias"
            value={alias}
            disabled={demoModeActive}
            onChange={(event) => setAlias(event.target.value)}
            className="rounded border border-white/10 bg-zinc-950 p-1 text-xs"
          />
          <button
            type="button"
            disabled={demoModeActive || !alias.trim()}
            onClick={() => {
              void reconcile({
                operation: "add_alias",
                entity_id: entity.id,
                alias,
              });
              setAlias("");
            }}
            className="ml-2 text-xs text-[#7EB3FF] disabled:opacity-45"
          >
            Add alias
          </button>
          <select
            aria-label="Merge entity into"
            value={target}
            disabled={demoModeActive}
            onChange={(event) => setTarget(event.target.value)}
            className="block rounded border border-white/10 bg-zinc-950 p-1 text-xs"
          >
            <option value="">Merge into…</option>
            {inspector.entities
              .filter((item) => item.id !== entity.id)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
          {target ? (
            <button
              type="button"
              disabled={demoModeActive}
              onClick={() =>
                void reconcile({
                  operation: "merge_entities",
                  source_entity_id: entity.id,
                  target_entity_id: target,
                })
              }
              className="text-xs text-amber-200 disabled:opacity-45"
            >
              Propose entity merge
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ReviewPanel({
  inspector,
  demoModeActive,
  onOpenActions,
}: {
  inspector: Inspector;
  demoModeActive: boolean;
  onOpenActions: (actionId: string) => void;
}): ReactElement {
  const toggle = (
    decision: Inspector["reviewFilters"]["decisions"][number],
  ): void => {
    inspector.setReviewFilters((current) => {
      if (current.decisions.includes(decision)) {
        if (current.decisions.length === 1) return current;
        return { decisions: current.decisions.filter((item) => item !== decision) };
      }
      return { decisions: [...current.decisions, decision] };
    });
  };
  const review = inspector.reviewDetail;
  return (
    <div
      id="context-review-panel"
      role="tabpanel"
      aria-labelledby="context-review-tab"
      className="space-y-3"
    >
      <div className="flex flex-wrap gap-2">
        {REVIEW_DECISIONS.map((decision) => (
          <label key={decision} className="text-xs text-zinc-400">
            <input
              type="checkbox"
              checked={inspector.reviewFilters.decisions.includes(decision)}
              onChange={() => toggle(decision)}
            />{" "}
            {decision.replaceAll("_", " ")}
          </label>
        ))}
      </div>
      {inspector.isLoading ? (
        <p className="text-xs text-zinc-500">Loading reviews…</p>
      ) : null}
      {inspector.reviews.length >= 100 ? (
        <p className="text-xs text-amber-200">
          Showing the newest 100 reviews. Refine the filters to narrow the list.
        </p>
      ) : null}
      {!inspector.isLoading && !inspector.reviews.length ? (
        <p className="text-xs text-zinc-500">No reviews match these filters.</p>
      ) : null}
      {inspector.reviews.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => void inspector.selectReview(item.id)}
          className="block w-full rounded border border-white/10 p-2 text-left text-xs"
        >
          <span className={statusClass(item.decision)}>{item.decision}</span> · {item.operation} ·{" "}
          {item.created_at} · {proposalSummary(item)} ·{" "}
          {item.reason_codes.map((code) => code.replaceAll("_", " ")).join(", ") || "No reason recorded"}
        </button>
      ))}
      {inspector.isReviewLoading ? (
        <p className="flex gap-2 text-xs text-zinc-500">
          <Loader2 className="size-3 animate-spin" />
          Loading review…
        </p>
      ) : null}
      {review ? (
        <div className="space-y-2 rounded border border-white/10 p-3">
          <p className="text-xs text-amber-200">
            Reason: {review.reason_codes.map((code) => code.replaceAll("_", " ")).join(", ") || "No reason recorded"}
          </p>
          <div>
            <p className="font-mono text-[10px] uppercase text-zinc-500">
              Current information
            </p>
            {inspector.reviewRecords.length ? (
              inspector.reviewRecords.map((record) => (
                <p key={record.id} className="text-xs text-zinc-200">
                  {record.kind} · {record.status} · {record.effective_at ?? "Not recorded"} · {record.text}
                </p>
              ))
            ) : (
              <p className="text-xs text-zinc-500">
                No current record is available.
              </p>
            )}
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase text-zinc-500">
              Proposed information
            </p>
            <p className="text-xs text-amber-100">{proposalSummary(review)}</p>
            <p className="text-xs text-zinc-500">
              {proposalEvidence(review)}
            </p>
          </div>
          {review.action_id ? (
            <button
              type="button"
              onClick={() => onOpenActions(review.action_id!)}
              className="text-xs text-[#7EB3FF]"
            >
              Open linked action
            </button>
          ) : null}
          {inspector.reviewRefreshRequired ? (
            <div>
              <p role="alert" className="text-xs text-amber-200">
                Context changed. Refresh this review before deciding again.
              </p>
              <button
                type="button"
                disabled={demoModeActive || Boolean(inspector.reviewMutation)}
                onClick={() => void inspector.decideReview("refresh")}
                className="text-xs text-[#7EB3FF] disabled:opacity-45"
              >
                Refresh review
              </button>
            </div>
          ) : null}
          {review.decision === "pending" ? (
            <div className="flex gap-2">
              <button
                type="button"
                disabled={
                  demoModeActive ||
                  Boolean(inspector.reviewMutation) ||
                  inspector.reviewRefreshRequired
                }
                onClick={() => void inspector.decideReview("accept")}
                className="text-xs text-emerald-200 disabled:opacity-45"
              >
                Accept
              </button>
              <button
                type="button"
                disabled={
                  demoModeActive ||
                  Boolean(inspector.reviewMutation) ||
                  inspector.reviewRefreshRequired
                }
                onClick={() => void inspector.decideReview("reject")}
                className="text-xs text-red-200 disabled:opacity-45"
              >
                Reject
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function CortexContext({
  inspector,
  demoModeActive,
  onOpenActions,
}: {
  inspector: Inspector;
  demoModeActive: boolean;
  onOpenActions: (actionId: string) => void;
}): ReactElement {
  const [view, setView] = useState<View>("records");
  const [showCapture, setShowCapture] = useState(false);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const { searchEntities } = inspector;
  useEffect(() => {
    queueMicrotask(() => void searchEntities());
  }, [searchEntities]);
  const selectView = (next: View): void => {
    setView(next);
    tabs.current[next === "records" ? 0 : 1]?.focus();
  };
  const openReview = (reviewId: string): void => {
    setView("review");
    void inspector.selectReview(reviewId);
  };
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    const index = view === "records" ? 0 : 1;
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? 1
          : event.key === "ArrowRight"
            ? (index + 1) % 2
            : event.key === "ArrowLeft"
              ? (index + 1) % 2
              : null;
    if (next === null) return;
    event.preventDefault();
    selectView(next === 0 ? "records" : "review");
  };
  const save = async (
    input: ContextCaptureInput,
    correction = false,
  ): Promise<"saved" | "review_required" | null> =>
    (
      await inspector.save(
        correction && inspector.detail
          ? {
              ...input,
              correction_record_id: inspector.detail.id,
              expected_updated_at: inspector.detail.updated_at,
            }
          : input,
      )
    )?.outcome ?? null;
  const toggleStatus = (
    status: Inspector["filters"]["statuses"][number],
  ): void =>
    inspector.setFilters((current) => ({
      ...current,
      statuses: current.statuses.includes(status)
        ? current.statuses.filter((item) => item !== status)
        : [...current.statuses, status],
    }));
  return (
    <section className="space-y-3" aria-label="Personal context">
      <div className="flex justify-between gap-2">
        <p className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500">
          Personal context
        </p>
        <button
          type="button"
          disabled={demoModeActive}
          onClick={() => setShowCapture((current) => !current)}
          className="text-xs text-[#7EB3FF] disabled:opacity-45"
        >
          {showCapture ? "Close" : "Capture"}
        </button>
      </div>
      {demoModeActive ? (
        <p className="text-xs text-zinc-500">
          Context changes are unavailable in demo mode.
        </p>
      ) : null}
      {showCapture ? (
        <SaveForm
          label="Manual context"
          disabled={demoModeActive}
          onSave={save}
        />
      ) : null}
      {inspector.error ? (
        <p role="alert" className="text-xs text-red-200">
          {inspector.error}
        </p>
      ) : null}
      <div role="tablist" aria-label="Context views">
        <button
          ref={(node) => {
            tabs.current[0] = node;
          }}
          id="context-records-tab"
          role="tab"
          aria-controls="context-records-panel"
          aria-selected={view === "records"}
          tabIndex={view === "records" ? 0 : -1}
          onKeyDown={onTabKeyDown}
          onClick={() => setView("records")}
          className="p-2 text-xs"
        >
          Records
        </button>
        <button
          ref={(node) => {
            tabs.current[1] = node;
          }}
          id="context-review-tab"
          role="tab"
          aria-controls="context-review-panel"
          aria-selected={view === "review"}
          tabIndex={view === "review" ? 0 : -1}
          onKeyDown={onTabKeyDown}
          onClick={() => setView("review")}
          className="p-2 text-xs"
        >
          Review ({inspector.pendingReviewCount})
        </button>
      </div>
      {view === "records" ? (
        <div
          id="context-records-panel"
          role="tabpanel"
          aria-labelledby="context-records-tab"
          className="space-y-3"
        >
          <div className="rounded border border-white/10 p-3 text-xs text-zinc-400">
            Retrieval: {inspector.retrieval?.mode ?? "loading"} ·{" "}
            {inspector.retrieval
              ? `${inspector.retrieval.indexed_items} indexed · ${inspector.retrieval.pending_items} pending`
              : "Loading local retrieval status…"}
            {inspector.retrieval &&
            ["unprepared", "degraded"].includes(inspector.retrieval.state) ? (
              <button
                type="button"
                disabled={demoModeActive || inspector.isPreparing}
                onClick={() => void inspector.prepare()}
                className="ml-2 text-[#7EB3FF] disabled:opacity-45"
              >
                {inspector.isPreparing
                  ? "Preparing…"
                  : "Prepare semantic retrieval"}
              </button>
            ) : null}
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void inspector.refresh();
            }}
            className="space-y-2"
          >
            <input
              aria-label="Search personal context"
              value={inspector.filters.query}
              onChange={(event) =>
                inspector.setFilters((current) => ({
                  ...current,
                  query: event.target.value,
                }))
              }
              className="w-full rounded border border-white/10 bg-zinc-950 p-2 text-xs"
            />
            <select
              aria-label="Context kind"
              value={inspector.filters.kind}
              onChange={(event) =>
                inspector.setFilters((current) => ({
                  ...current,
                  kind: event.target.value as ContextKind | "",
                }))
              }
              className="w-full rounded border border-white/10 bg-zinc-950 p-2 text-xs"
            >
              <option value="">All kinds</option>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
            <div>
              {STATUSES.map((status) => (
                <label key={status} className="mr-2 text-xs">
                  <input
                    type="checkbox"
                    checked={inspector.filters.statuses.includes(status)}
                    onChange={() => toggleStatus(status)}
                  />{" "}
                  {status}
                </label>
              ))}
            </div>
            <button type="submit" className="text-xs text-[#7EB3FF]">
              Search
            </button>
          </form>
          {inspector.isLoading ? (
            <p className="flex gap-2 text-xs text-zinc-500">
              <Loader2 className="size-3 animate-spin" />
              Loading context…
            </p>
          ) : null}
          {inspector.records.length >= 100 ? (
            <p className="text-xs text-amber-200">
              Showing the newest 100 records. Refine the filters to narrow the
              list.
            </p>
          ) : null}
          {!inspector.isLoading && !inspector.records.length ? (
            <p className="text-xs text-zinc-500">
              No context records match these filters.
            </p>
          ) : null}
          <div className="space-y-1">
            {inspector.records.map((record) => (
              <RecordRow
                key={record.id}
                record={record}
                selected={record.id === inspector.selectedRecordId}
                onSelect={() => void inspector.selectRecord(record.id)}
              />
            ))}
          </div>
          {inspector.isDetailLoading ? (
            <p className="text-xs text-zinc-500">Loading record details…</p>
          ) : null}
          <RecordDetail
            key={inspector.detail?.id}
            inspector={inspector}
            demoModeActive={demoModeActive}
            onOpenReview={openReview}
            onSave={save}
          />
          {inspector.lastCreatedRecordId ? (
            <button
              type="button"
              disabled={demoModeActive}
              onClick={() =>
                void inspector.reconcile({
                  operation: "retract",
                  record_id: inspector.lastCreatedRecordId!,
                })
              }
              className="text-xs text-amber-200 disabled:opacity-45"
            >
              Undo recent saved context
            </button>
          ) : null}
        </div>
      ) : (
        <ReviewPanel
          inspector={inspector}
          demoModeActive={demoModeActive}
          onOpenActions={onOpenActions}
        />
      )}
    </section>
  );
}
