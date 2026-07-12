export type ConsoleActivityTone = 'rust' | 'purple'

export function resolveConsoleActivityTone(
  isAssistantQuerying: boolean,
  isLocalModelLoading: boolean,
): ConsoleActivityTone | null {
  if (!isAssistantQuerying) {
    return null
  }
  return isLocalModelLoading ? 'rust' : 'purple'
}
