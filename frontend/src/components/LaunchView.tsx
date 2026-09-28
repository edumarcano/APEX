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
  { id: 'reports', label: 'Reports', icon: Newspaper, tone: 'hover:border-cyan-400/45 hover:text-cyan-100 focus-visible:outline-cyan-300' },
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, tone: 'hover:border-blue-400/45 hover:text-blue-100 focus-visible:outline-blue-300' },
  { id: 'briefing', label: 'Briefing', icon: AudioLines, tone: 'hover:border-amber-300/45 hover:text-amber-100 focus-visible:outline-amber-300' },
  { id: 'cortex', label: 'Cortex', icon: BrainCircuit, tone: 'hover:border-purple-400/45 hover:text-purple-100 focus-visible:outline-purple-300' },
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
  return <section className="h-full min-h-0 w-full flex-1 flex-col items-center justify-center gap-6 flex" aria-label="Launch">
    <ApexLogo {...logoProps} className="h-24 w-auto sm:h-28" />
    <h1 className="font-orbitron text-lg font-semibold uppercase tracking-[0.3em] text-[color:var(--hud-text)]">APEX</h1>
    <nav aria-label="Workspace" className="grid w-full max-w-3xl grid-cols-2 gap-2.5 sm:grid-cols-4 sm:gap-3">
      {LAUNCH_WORKSPACES.map(({ id, label, icon: Icon, tone }) => <button
        key={id}
        type="button"
        onClick={() => onSelect(id)}
        aria-current={current === id ? 'page' : undefined}
        className={`hud-interactive-shell hud-glass flex min-h-12 items-center justify-center gap-2 rounded-xl border border-white/10 bg-zinc-950/35 px-4 py-3 font-orbitron text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-300 transition-[border-color,background-color,color,box-shadow] duration-200 hover:bg-white/[0.07] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${tone}`}
      >
        <Icon className="size-4 shrink-0 opacity-75" aria-hidden="true" />
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
