import type { ReactElement } from 'react'

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
  size: 'hero' | 'large' | 'overview' | 'compact'
}): ReactElement {
  const logoClass = size === 'hero'
    ? 'hud-logo-mark h-48 w-auto sm:h-56 xl:h-64'
    : size === 'large'
      ? 'hud-logo-mark h-40 w-auto sm:h-48 xl:h-56'
      : size === 'overview'
        ? 'h-24 w-auto sm:h-28'
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
