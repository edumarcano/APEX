import type { ReactElement } from 'react'

import type { HomeActiveView } from '../../hooks/useHomeView'
import { ApexLogo, type ApexLogoProps } from '../ApexLogo'
import { VoiceSignalGlyph, type VoiceSignalGlyphProps } from '../VoiceSignalGlyph'

export type HomeIdentityProps = {
  logoProps: Omit<ApexLogoProps, 'className'>
  glyphProps: VoiceSignalGlyphProps
}

const LOGO_GLOW_CLASS = 'filter drop-shadow-[0_0_24px_rgba(var(--logo-glow-color),0.45)] transition-[filter] duration-1000 motion-reduce:transition-none'

export function HomeIdentityMark({
  identity,
  size,
}: {
  identity: HomeIdentityProps
  size: 'hero' | 'large' | 'compact'
}): ReactElement {
  const logoClass = size === 'hero'
    ? 'hud-logo-mark h-48 w-auto sm:h-56 xl:h-64'
    : size === 'large'
      ? 'hud-logo-mark h-40 w-auto sm:h-48 xl:h-56'
      : 'h-16 w-auto sm:h-20'
  return <div className="relative flex flex-col items-center" data-slot="home-identity">
    <div className={`${LOGO_GLOW_CLASS} ${size === 'hero' ? 'scale-115 xl:scale-125' : ''}`}>
      <ApexLogo {...identity.logoProps} className={logoClass} />
    </div>
    <div className={`flex flex-col items-center whitespace-nowrap ${size === 'hero' ? 'mt-7 xl:mt-9' : 'mt-2'}`}>
      <VoiceSignalGlyph {...identity.glyphProps} />
    </div>
  </div>
}

export function HomeViewSwitcher({
  view,
  onSelectView,
  onReturnToStandby,
}: {
  view: HomeActiveView
  onSelectView: (view: HomeActiveView) => void
  onReturnToStandby: () => void
}): ReactElement {
  const buttonClass = (active: boolean): string => `rounded-md px-2.5 py-1.5 font-orbitron text-[10px] uppercase tracking-[0.14em] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#7EB3FF] ${active ? 'bg-[#0F4DB8]/20 text-[#A5C7FF]' : 'text-zinc-500 hover:text-zinc-200'}`
  return <nav className="flex flex-wrap items-center justify-center gap-1" aria-label="Home view">
    <button type="button" aria-pressed={view === 'overview'} onClick={() => onSelectView('overview')} className={buttonClass(view === 'overview')}>Overview</button>
    <button type="button" aria-pressed={view === 'briefing'} onClick={() => onSelectView('briefing')} className={buttonClass(view === 'briefing')}>Briefing</button>
    <button type="button" onClick={onReturnToStandby} className={buttonClass(false)}>Standby</button>
  </nav>
}
