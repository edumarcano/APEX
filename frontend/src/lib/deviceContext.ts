import { API_ENDPOINTS } from './api'

export type DevicePermission = 'unknown' | 'granted' | 'denied' | 'revoked' | 'unsupported'
export type DeviceAvailability = 'unknown' | 'available' | 'unavailable' | 'timed_out' | 'unsupported'
export type DeviceLocationSource = 'device' | 'configured' | 'none'
export type DeviceLocationFreshness = 'none' | 'fresh' | 'expired'

export interface DeviceContextStatus {
  enabled: boolean
  permission: DevicePermission
  availability: DeviceAvailability
  source: DeviceLocationSource
  freshness: DeviceLocationFreshness
  fix_age_seconds: number | null
}

export const DEVICE_CONTEXT_STATUS_TIMEOUT_MS = 3_000

/** Convert known native command failures to safe, actionable UI copy. */
export function locationPermissionErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : ''
  if (message.includes('foreground_required')) return 'Bring the APEX window to the foreground before checking location permission.'
  if (message.includes('preferences_unavailable')) return 'The saved location preference has not reached the desktop service yet. Try again shortly.'
  if (message.includes('stale_request')) return 'The location permission check became stale. Try again.'
  if (message.includes('backend_unavailable')) return 'The backend is unavailable. Try again when it is ready.'
  return 'Windows could not check location permission. Try again.'
}

const permissions: readonly DevicePermission[] = ['unknown', 'granted', 'denied', 'revoked', 'unsupported']
const availabilities: readonly DeviceAvailability[] = ['unknown', 'available', 'unavailable', 'timed_out', 'unsupported']
const sources: readonly DeviceLocationSource[] = ['device', 'configured', 'none']
const freshnesses: readonly DeviceLocationFreshness[] = ['none', 'fresh', 'expired']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Parse the coordinate-free, exact device-context status contract. */
export function parseDeviceContextStatus(value: unknown): DeviceContextStatus | null {
  if (!isRecord(value)) return null
  const keys = ['enabled', 'permission', 'availability', 'source', 'freshness', 'fix_age_seconds']
  if (Object.keys(value).length !== keys.length || !keys.every((key) => key in value)) return null
  if (
    typeof value.enabled !== 'boolean' ||
    typeof value.permission !== 'string' || !permissions.includes(value.permission as DevicePermission) ||
    typeof value.availability !== 'string' || !availabilities.includes(value.availability as DeviceAvailability) ||
    typeof value.source !== 'string' || !sources.includes(value.source as DeviceLocationSource) ||
    typeof value.freshness !== 'string' || !freshnesses.includes(value.freshness as DeviceLocationFreshness) ||
    !(value.fix_age_seconds === null || (typeof value.fix_age_seconds === 'number' && Number.isFinite(value.fix_age_seconds) && value.fix_age_seconds >= 0))
  ) return null
  return {
    enabled: value.enabled,
    permission: value.permission as DevicePermission,
    availability: value.availability as DeviceAvailability,
    source: value.source as DeviceLocationSource,
    freshness: value.freshness as DeviceLocationFreshness,
    fix_age_seconds: value.fix_age_seconds as number | null,
  }
}

export async function fetchDeviceContextStatus(signal?: AbortSignal): Promise<DeviceContextStatus> {
  const controller = new AbortController()
  let timedOut = false
  const abortFromCaller = () => controller.abort(signal?.reason)
  if (signal?.aborted) abortFromCaller()
  else signal?.addEventListener('abort', abortFromCaller, { once: true })
  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, DEVICE_CONTEXT_STATUS_TIMEOUT_MS)
  try {
    const response = await fetch(API_ENDPOINTS.deviceContext, { signal: controller.signal })
    if (!response.ok) throw new Error('Device location status could not be loaded.')
    const status = parseDeviceContextStatus(await response.json())
    if (!status) throw new Error('Device location status response was malformed.')
    return status
  } catch (error) {
    if (timedOut) throw new Error('Device location status request timed out.', { cause: error })
    throw error
  } finally {
    globalThis.clearTimeout(timeoutId)
    signal?.removeEventListener('abort', abortFromCaller)
  }
}
