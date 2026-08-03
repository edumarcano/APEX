/** Format a catalog display name for compact surfaces such as the composer. */
export function agentShortName(displayName: string): string {
  return displayName.replace(/^Apex\s+/i, '')
}
