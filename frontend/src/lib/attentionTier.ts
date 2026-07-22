import type { SystemState } from '../types/telemetry'

/** Visual attention state for HUD telemetry surfaces. */
export type AttentionTier = 'dormant' | 'pending' | 'active' | 'complete'

/** Surfaces that participate in the pipeline reveal sequence. */
export type AttentionSurfaceId =
  | 'reminders'
  | 'weather'
  | 'news'
  | 'events'
  | 'market'
  | 'inbox'
  | 'insights'

type SurfaceSchedule = {
  /** Pipeline step at which this surface becomes the focus. */
  activeAt: number
  /** Pipeline step at which this surface is considered ready. */
  completeAt: number
  /** Curtain transition delay (ms) when unlocking within a shared step. */
  staggerMs: number
}

/**
 * Reveal order by data source latency:
 * 1. Reminders (local DB) — gate
 * 2. Weather + News (public APIs) — unlock during collection
 * 3. Events + Market + Inbox (heavier / auth’d APIs) — active through collection
 * 4. Insights (AI synthesis) — synthesis → delivery
 */
const SURFACE_SCHEDULE: Record<AttentionSurfaceId, SurfaceSchedule> = {
  reminders: { activeAt: 1, completeAt: 2, staggerMs: 0 },
  weather: { activeAt: 2, completeAt: 2, staggerMs: 0 },
  news: { activeAt: 2, completeAt: 2, staggerMs: 120 },
  events: { activeAt: 2, completeAt: 3, staggerMs: 280 },
  market: { activeAt: 2, completeAt: 3, staggerMs: 360 },
  inbox: { activeAt: 2, completeAt: 3, staggerMs: 440 },
  insights: { activeAt: 3, completeAt: 4, staggerMs: 0 },
}

/**
 * Maps pipeline step + system status to a shared attention tier.
 * Presentation-only; does not alter backend contracts.
 */
export function resolveAttentionTier(
  surface: AttentionSurfaceId,
  step: number | null,
  status: SystemState,
): AttentionTier {
  if (status === 'idle') {
    return 'dormant'
  }

  if (status === 'error' || status === 'success') {
    return 'complete'
  }

  // loading with no step yet — treat as gate
  const activeStep = step ?? 1
  if (activeStep >= 4) {
    return 'complete'
  }

  const { activeAt, completeAt } = SURFACE_SCHEDULE[surface]

  // Same-step unlock (e.g. weather/news): spotlight during that step, settle after.
  if (activeAt === completeAt) {
    if (activeStep > completeAt) {
      return 'complete'
    }
    if (activeStep >= activeAt) {
      return 'active'
    }
    return 'pending'
  }

  if (activeStep >= completeAt) {
    return 'complete'
  }
  if (activeStep >= activeAt) {
    return 'active'
  }
  return 'pending'
}

/**
 * Attention for Start APEX / telemetry-only collection (no briefing pipeline).
 * Activated overview reveals cards during refresh without briefing stages.
 */
export function resolveTelemetryAttentionTier(
  surface: AttentionSurfaceId,
  options: {
    activated: boolean
    isRefreshing: boolean
    hasSnapshot: boolean
    briefingStatus: SystemState | null
    briefingStep: number | null
  },
): AttentionTier {
  const { activated, isRefreshing, hasSnapshot, briefingStatus, briefingStep } = options

  if (!activated) {
    return 'dormant'
  }

  // While a briefing run is active, keep the existing pipeline-tied schedule.
  if (briefingStatus === 'loading') {
    return resolveAttentionTier(surface, briefingStep, briefingStatus)
  }

  if (surface === 'insights') {
    if (briefingStatus === 'success' || briefingStatus === 'error') {
      return 'complete'
    }
    return hasSnapshot ? 'complete' : isRefreshing ? 'pending' : 'active'
  }

  if (isRefreshing && !hasSnapshot) {
    return surface === 'reminders' ? 'complete' : 'active'
  }

  return 'complete'
}

/** Curtain stagger delay for surfaces that share a pipeline step. */
export function resolveAttentionStaggerMs(surface: AttentionSurfaceId): number {
  return SURFACE_SCHEDULE[surface].staggerMs
}

/** CSS class applied to the card/digest shell for the given tier. */
export function attentionShellClass(tier: AttentionTier): string {
  return `attention-shell attention-shell--${tier}`
}

/** Whether body content should run the curtain unmask. */
export function attentionCurtainRevealed(tier: AttentionTier): boolean {
  // Idle stays open; pending masks body; active/complete unmask.
  return tier !== 'pending'
}
