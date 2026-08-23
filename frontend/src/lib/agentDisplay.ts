/** Format a catalog display name for compact surfaces such as small pills, badges, or mobile controls. */
export function agentShortName(displayName: string): string {
  return displayName.replace(/^Apex\s+/i, '')
}

/** Return the canonical presentation descriptor for an Agent. */
export function agentDescriptor(agentKeyOrDisplayName: string): string {
  const normalized = agentKeyOrDisplayName.toLowerCase()
  if (normalized.includes('cloud') || normalized.includes('panthera')) {
    return 'Cloud · Generalist'
  }
  if (normalized.includes('local') || normalized.includes('felis')) {
    return 'Local · Private'
  }
  return ''
}
