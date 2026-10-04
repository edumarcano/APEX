export function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value || [...value].some((character) => {
    const code = character.charCodeAt(0)
    return code <= 31 || code === 127
  })) return null
  try {
    const url = new URL(value)
    if ((url.protocol !== 'https:' && url.protocol !== 'http:') || !url.hostname || url.username || url.password) return null
    return url.toString()
  } catch {
    return null
  }
}
