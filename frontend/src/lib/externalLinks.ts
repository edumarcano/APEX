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

export function safeInternalHref(value: string | null | undefined, baseHref?: string): string | null {
  if (!value || [...value].some((character) => {
    const code = character.charCodeAt(0)
    return code <= 31 || code === 127
  }) || value.startsWith('//')) return null
  try {
    const base = baseHref ?? (typeof window === 'undefined' ? 'http://localhost/' : window.location.href)
    const target = new URL(value, base)
    const current = new URL(base)
    if ((target.protocol !== 'http:' && target.protocol !== 'https:') || target.origin !== current.origin || target.username || target.password) return null
    return value
  } catch {
    return null
  }
}
