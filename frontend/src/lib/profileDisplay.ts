/** Format a catalog display name for compact surfaces such as the composer. */
export function profileShortName(displayName: string): string {
  return displayName.replace(/^APEX\s+/i, '')
}
