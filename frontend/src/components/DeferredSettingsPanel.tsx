import { useEffect, useRef, useState, type ComponentProps, type ReactElement, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'

import type SettingsPanel from './SettingsPanel'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { DeferredPresentation } from './DeferredPresentation'

type Props = ComponentProps<typeof SettingsPanel>

const loadSettingsPanel = () => import('./SettingsPanel')

export function DeferredSettingsPanel(props: Props): ReactElement | null {
  const [hasOpened, setHasOpened] = useState(props.open)
  if (props.open && !hasOpened) setHasOpened(true)

  if (!hasOpened) return null

  return <DeferredPresentation
    load={loadSettingsPanel}
    componentProps={props}
    fallback={<SettingsLoadingDialog open={props.open} onClose={props.onClose} restoreFocusRef={props.restoreFocusRef} />}
    renderError={(retry) => <SettingsLoadErrorDialog open={props.open} onClose={props.onClose} restoreFocusRef={props.restoreFocusRef} retry={retry} />}
  />
}

function SettingsLoadingDialog({ open, onClose, restoreFocusRef }: Pick<Props, 'open' | 'onClose' | 'restoreFocusRef'>): ReactElement | null {
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(open, dialogRef, restoreFocusRef)
  useEscapeClose(open, onClose)
  if (!open) return null

  return createPortal(<DialogShell title="Loading settings" dialogRef={dialogRef}>
    <p className="text-sm text-zinc-300" role="status">Loading settings…</p>
    <div className="mt-5 flex justify-end">
      <DialogButton onClick={onClose}>Close</DialogButton>
    </div>
  </DialogShell>, document.body)
}

function SettingsLoadErrorDialog({ open, onClose, restoreFocusRef, retry }: Pick<Props, 'open' | 'onClose' | 'restoreFocusRef'> & { retry: () => void }): ReactElement | null {
  const dialogRef = useRef<HTMLDivElement>(null)
  useFocusTrap(open, dialogRef, restoreFocusRef)
  useEscapeClose(open, onClose)
  if (!open) return null

  return createPortal(<DialogShell title="Settings could not load" dialogRef={dialogRef}>
    <p className="text-sm leading-relaxed text-zinc-300" role="alert">The settings panel failed to load. Retry the load or reload APEX.</p>
    <div className="mt-5 flex flex-wrap justify-end gap-2">
      <DialogButton onClick={onClose}>Close</DialogButton>
      <DialogButton onClick={retry}>Retry</DialogButton>
      <DialogButton onClick={() => { if (window.confirm('Reload APEX? Reloading will discard unsent text.')) window.location.reload() }}>Reload APEX</DialogButton>
    </div>
  </DialogShell>, document.body)
}

function useEscapeClose(open: boolean, onClose: () => void): void {
  useEffect(() => {
    if (!open) return undefined
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose, open])
}

function DialogShell({ title, dialogRef, children }: { title: string; dialogRef: RefObject<HTMLDivElement | null>; children: ReactNode }): ReactElement {
  const titleId = title === 'Loading settings' ? 'settings-loading-title' : 'settings-load-error-title'
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" role="presentation">
    <div ref={dialogRef} className="w-full max-w-lg rounded-xl border border-white/15 bg-zinc-950 p-5 shadow-2xl" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <h2 id={titleId} className="font-orbitron text-sm font-semibold tracking-[0.12em] text-white">{title}</h2>
      <div className="mt-3">{children}</div>
    </div>
  </div>
}

function DialogButton({ onClick, children }: { onClick: () => void; children: ReactNode }): ReactElement {
  return <button type="button" onClick={onClick} className="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-sm text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400">{children}</button>
}
