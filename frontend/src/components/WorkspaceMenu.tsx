import { ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef, useState, type ReactElement } from 'react'

export type WorkspacePeer = 'inbox' | 'overview' | 'briefing' | 'cortex'

const PEERS: Array<{ id: WorkspacePeer; label: string; activeClass: string }> = [
  { id: 'inbox', label: 'Inbox', activeClass: 'bg-[#FBBF24]/15 text-[#FFF3B0]' },
  { id: 'overview', label: 'Overview', activeClass: 'bg-[#0F4DB8]/20 text-[#A5C7FF]' },
  { id: 'briefing', label: 'Briefing', activeClass: 'bg-[#0F4DB8]/20 text-[#A5C7FF]' },
  { id: 'cortex', label: 'Cortex', activeClass: 'bg-[#7E22CE]/25 text-[#D8B4FE]' },
]

/** Header chip that switches between peer workspaces. Standby is a state, not a peer. */
export function WorkspaceMenu({
  current,
  onSelect,
}: {
  current: WorkspacePeer
  onSelect: (peer: WorkspacePeer) => void
}): ReactElement {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  const currentPeer = PEERS.find((peer) => peer.id === current) ?? PEERS[1]

  useEffect(() => {
    if (!open) return
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      setOpen(false)
      buttonRef.current?.focus()
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  return <div ref={rootRef} className="relative flex justify-center">
    <button
      ref={buttonRef}
      type="button"
      aria-label="Workspace"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      onClick={() => setOpen((value) => !value)}
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${currentPeer.activeClass}`}
    >
      <span>{currentPeer.label}</span>
      <ChevronDown className={`size-3 transition-transform ${open ? 'rotate-180' : ''}`} strokeWidth={2} aria-hidden />
    </button>
    {open ? (
      <div
        id={menuId}
        role="menu"
        aria-label="Workspace"
        className="hud-glass hud-glass-solid absolute left-1/2 top-full z-50 mt-1 flex min-w-[8.5rem] -translate-x-1/2 flex-col gap-0.5 rounded-lg border border-white/10 p-1 shadow-2xl"
      >
        {PEERS.map((peer) => {
          const selected = peer.id === current
          return <button
            key={peer.id}
            type="button"
            role="menuitemradio"
            aria-checked={selected}
            onClick={() => {
              setOpen(false)
              onSelect(peer.id)
            }}
            className={`rounded-md px-2.5 py-1.5 text-left font-orbitron text-[10px] uppercase tracking-[0.14em] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7EB3FF] ${selected ? peer.activeClass : 'text-zinc-500 hover:text-zinc-200'}`}
          >
            {peer.label}
          </button>
        })}
      </div>
    ) : null}
  </div>
}
