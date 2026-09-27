import type { ReactElement } from 'react'

export type WorkspacePeer = 'inbox' | 'overview' | 'briefing' | 'cortex'

const PEERS: Array<{ id: WorkspacePeer; label: string; activeClass: string }> = [
  { id: 'inbox', label: 'Inbox', activeClass: 'bg-[#FBBF24]/15 text-[#FFF3B0]' },
  { id: 'overview', label: 'Overview', activeClass: 'bg-[#0F4DB8]/20 text-[#A5C7FF]' },
  { id: 'briefing', label: 'Briefing', activeClass: 'bg-[#FBBF24]/15 text-[#FFF3B0]' },
  { id: 'cortex', label: 'Cortex', activeClass: 'bg-[#7E22CE]/25 text-[#D8B4FE]' },
]

/** Visible header tabs for the four peer workspaces. Standby is a state, not a peer. */
export function WorkspaceTabs({
  current,
  onSelect,
}: {
  current: WorkspacePeer
  onSelect: (peer: WorkspacePeer) => void
}): ReactElement {
  return (
    <nav
      aria-label="Workspace"
      className="flex w-full items-center justify-center gap-0.5"
      role="navigation"
    >
      {PEERS.map((peer) => {
        const selected = peer.id === current
        return (
          <button
            key={peer.id}
            type="button"
            onClick={() => onSelect(peer.id)}
            aria-current={selected ? 'page' : undefined}
            className={`rounded-md px-2 py-1 font-orbitron text-[9px] uppercase tracking-[0.12em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#7EB3FF] sm:text-[10px] sm:tracking-[0.14em] ${selected ? peer.activeClass : 'text-zinc-500 hover:text-zinc-200'}`}
          >
            {peer.label}
          </button>
        )
      })}
    </nav>
  )
}
