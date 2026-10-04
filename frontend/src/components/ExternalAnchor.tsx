import type { AnchorHTMLAttributes, MouseEvent, ReactElement } from 'react'

import { isNativeDesktop, openExternal } from '../platform/services'
import { safeExternalUrl } from '../lib/externalLinks'

export function ExternalAnchor({ href, onClick, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>): ReactElement {
  const safeUrl = safeExternalUrl(href)
  if (!safeUrl) return <span>{children}</span>

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (event.defaultPrevented || !isNativeDesktop()) return
    event.preventDefault()
    void openExternal(safeUrl).catch(() => undefined)
  }

  return <a {...props} href={safeUrl} onClick={handleClick}>{children}</a>
}
