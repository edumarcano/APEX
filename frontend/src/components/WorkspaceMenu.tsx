import { ChevronDown } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'

export type WorkspacePeer = 'inbox' | 'overview' | 'briefing' | 'cortex'

const PEERS: Array<{ id: WorkspacePeer; label: string; activeClass: string }> = [
  { id: 'inbox', label: 'Inbox', activeClass: 'bg-[#FBBF24]/15 text-[#FFF3B0]' },
  { id: 'overview', label: 'Overview', activeClass: 'bg-[#0F4DB8]/20 text-[#A5C7FF]' },
  { id: 'briefing', label: 'Briefing', activeClass: 'bg-[#0F4DB8]/20 text-[#A5C7FF]' },
  { id: 'cortex', label: 'Cortex', activeClass: 'bg-[#7E22CE]/25 text-[#D8B4FE]' },
]

type MenuPosition = { left: number; top: number }

function positionForTrigger(trigger: HTMLElement | null): MenuPosition | null {
  if (!trigger) return null
  const rect = trigger.getBoundingClientRect()
  return {
    left: rect.left + rect.width / 2,
    top: rect.bottom + 4,
  }
}

/** Header chip that switches between peer workspaces. Standby is a state, not a peer. */
export function WorkspaceMenu({
  current,
  onSelect,
}: {
  current: WorkspacePeer
  onSelect: (peer: WorkspacePeer) => void
}): ReactElement {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<MenuPosition | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const currentPeer = PEERS.find((peer) => peer.id === current) ?? PEERS[1]

  useLayoutEffect(() => {
    if (!open) return
    setPosition(positionForTrigger(buttonRef.current))
  }, [open])

  useEffect(() => {
    if (!open) return
    const closeOnOutsidePointer = (event: PointerEvent): void => {
      const target = event.target as Node
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return
      setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      setOpen(false)
      buttonRef.current?.focus()
    }
    const updatePosition = (): void => {
      setPosition(positionForTrigger(buttonRef.current))
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('keydown', closeOnEscape)
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('keydown', closeOnEscape)
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
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
    {open && position && typeof document !== 'undefined' ? createPortal(
      <div
        ref={menuRef}
        id={menuId}
        role="menu"
        aria-label="Workspace"
        style={{ left: position.left, top: position.top }}
        className="hud-glass hud-glass-solid fixed z-[var(--z-overlay)] flex min-w-[8.5rem] -translate-x-1/2 flex-col gap-0.5 rounded-lg border border-white/10 p-1 shadow-2xl"
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
      </div>,
      document.body,
    ) : null}
  </div>
}
