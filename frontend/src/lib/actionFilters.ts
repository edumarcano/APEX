import type { ActionRecord } from '../types/actions'

export const RECENT_ACTION_WINDOW_MS = 24 * 60 * 60 * 1000

export function filterAndSortActions(
  actions: readonly ActionRecord[],
  nowMs: number = Date.now(),
): ActionRecord[] {
  const proposed: ActionRecord[] = []
  const recentResolved: ActionRecord[] = []

  for (const action of actions) {
    if (action.status === 'proposed') {
      proposed.push(action)
    } else {
      const updatedAtMs = Date.parse(action.updated_at)
      if (!Number.isNaN(updatedAtMs) && nowMs - updatedAtMs <= RECENT_ACTION_WINDOW_MS) {
        recentResolved.push(action)
      }
    }
  }

  proposed.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
  recentResolved.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))

  return [...proposed, ...recentResolved]
}
