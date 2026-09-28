import type { AgentAvailabilityStatus } from '../types/telemetry'

export type CloudAvailabilityPresentation = {
  label: string
  tone: 'success' | 'neutral' | 'error'
}

const BLOCKER_LABELS: Partial<Record<AgentAvailabilityStatus, string>> = {
  unauthorized: 'Access denied',
  model_unavailable: 'Unavailable',
  rate_limited: 'Rate limited',
  quota_exhausted: 'Quota exhausted',
  billing_blocked: 'Billing blocked',
  provider_unreachable: 'Unreachable',
  provider_error: 'Provider error',
  disabled: 'Unavailable',
}

/** Presents only known catalog and browser signals; it never probes a provider. */
export function cloudAvailabilityPresentation(
  status: AgentAvailabilityStatus | undefined,
  credentialsConfigured: boolean | undefined,
  browserOnline: boolean,
): CloudAvailabilityPresentation {
  if (credentialsConfigured === false) return { label: 'Access denied', tone: 'error' }

  const knownBlocker = status ? BLOCKER_LABELS[status] : undefined
  if (knownBlocker) return { label: knownBlocker, tone: 'error' }
  if (!browserOnline) return { label: 'Browser offline', tone: 'error' }

  if (status === 'available' || status === 'verified') {
    return { label: status === 'verified' ? 'Verified' : 'Ready', tone: 'success' }
  }

  if (status === 'busy') return { label: 'Busy', tone: 'neutral' }
  if (status === 'verifying') return { label: 'Verifying…', tone: 'neutral' }
  if (status === 'unknown') return { label: 'Checking…', tone: 'neutral' }
  return { label: 'Configured', tone: 'neutral' }
}
