import { Fragment, useState, type AnchorHTMLAttributes, type MouseEvent, type ReactElement } from 'react'

import { isNativeDesktop, openExternal } from '../platform/services'
import { safeExternalUrl, safeInternalHref } from '../lib/externalLinks'

export function ExternalAnchor({ href, onClick, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>): ReactElement {
  const safeUrl = safeExternalUrl(href)
  const internalHref = safeInternalHref(href)
  const [openError, setOpenError] = useState(false)
  if (!safeUrl && internalHref) return <a {...props} href={internalHref} onClick={onClick}>{children}</a>
  if (!safeUrl) return <span>{children}</span>

  const launch = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.currentTarget.hasAttribute('download') || !isNativeDesktop()) return
    event.preventDefault()
    setOpenError(false)
    void openExternal(safeUrl).catch(() => setOpenError(true))
  }

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event)
    if (event.button !== 0) return
    launch(event)
  }

  const handleAuxClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 1) return
    launch(event)
  }

  return <Fragment><a {...props} href={safeUrl} onClick={handleClick} onAuxClick={handleAuxClick}>{children}</a>{openError ? <span role="alert" className="ml-1 text-xs text-red-300">Could not open link. Copy the address and try again.</span> : null}</Fragment>
}
