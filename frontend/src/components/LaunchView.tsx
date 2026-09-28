import { AudioLines, BrainCircuit, LayoutDashboard, Newspaper, Settings, type LucideIcon } from 'lucide-react'
import type { ReactElement, RefObject } from 'react'

import { ApexLogo, type ApexLogoProps } from './ApexLogo'
import type { WorkspacePeer } from './WorkspaceTabs'

const LAUNCH_WORKSPACES: Array<{
  id: WorkspacePeer
  label: string
  icon: LucideIcon
  tone: string
}> = [
  { id: 'reports', label: 'Reports', icon: Newspaper, tone: 'border-[#22D3EE]/40 bg-[#22D3EE]/15 text-[#A5F3FC] hover:border-[#22D3EE]/70 hover:bg-[#22D3EE]/25 focus-visible:outline-[#22D3EE]' },
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, tone: 'border-[#0F4DB8]/50 bg-[#0F4DB8]/20 text-[#A5C7FF] hover:border-[#0F4DB8]/80 hover:bg-[#0F4DB8]/30 focus-visible:outline-[#A5C7FF]' },
  { id: 'briefing', label: 'Briefing', icon: AudioLines, tone: 'border-[#FBBF24]/40 bg-[#FBBF24]/15 text-[#FFF3B0] hover:border-[#FBBF24]/70 hover:bg-[#FBBF24]/25 focus-visible:outline-[#FBBF24]' },
  { id: 'cortex', label: 'Cortex', icon: BrainCircuit, tone: 'border-[#7E22CE]/50 bg-[#7E22CE]/25 text-[#D8B4FE] hover:border-[#7E22CE]/80 hover:bg-[#7E22CE]/35 focus-visible:outline-[#D8B4FE]' },
]

export function LaunchView({
  logoProps,
  current,
  onSelect,
  onOpenSettings,
  settingsButtonRef,
  mode,
}: {
  logoProps: Omit<ApexLogoProps, 'className'>
  current: WorkspacePeer | null
  onSelect: (peer: WorkspacePeer) => void
  onOpenSettings: () => void
  settingsButtonRef: RefObject<HTMLButtonElement | null>
  mode: 'DEMO' | 'DEVELOPER' | null
}): ReactElement {
  return <section className="h-full min-h-0 w-full flex-1 flex-col items-center justify-center gap-8 flex" aria-label="Launch">
    <div data-testid="launch-logo" className="filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] transform-gpu hover:filter hover:drop-shadow-[0_0_32px_rgba(var(--logo-glow-color),0.6)]">
      <ApexLogo {...logoProps} className="hud-logo-mark h-56 w-auto sm:h-64 xl:h-80" />
    </div>
    <h1 className="font-orbitron text-3xl font-semibold uppercase tracking-[0.3em] text-[#FBBF24] sm:text-4xl xl:text-5xl">APEX</h1>
    <nav aria-label="Workspace" className="grid w-full max-w-3xl grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
      {LAUNCH_WORKSPACES.map(({ id, label, icon: Icon, tone }) => <button
        key={id}
        type="button"
        onClick={() => onSelect(id)}
        aria-current={current === id ? 'page' : undefined}
        className={`hud-interactive-shell flex min-h-12 items-center justify-center gap-2 rounded-xl border px-4 py-3 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] transition-[border-color,background-color,color,box-shadow] duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${tone}`}
      >
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        {label}
      </button>)}
    </nav>
    <div className="flex items-center gap-3">
      {mode ? <span className={`rounded-full border px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.16em] ${mode === 'DEMO' ? 'border-amber-500/25 text-amber-300' : 'border-cyan-500/25 text-cyan-300'}`}>{mode}</span> : null}
      <button
        ref={settingsButtonRef}
        type="button"
        onClick={onOpenSettings}
        aria-label="Open settings"
        className="hud-interactive-shell hud-glass inline-flex h-9 items-center gap-2 rounded-full px-3 font-orbitron text-[9px] uppercase tracking-[0.14em] text-zinc-300 transition-colors hover:text-[color:var(--hud-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
      >
        <Settings className="size-3.5" aria-hidden="true" /> Settings
      </button>
    </div>
  </section>
}
