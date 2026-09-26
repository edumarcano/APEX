import type { ComponentProps, ReactElement } from 'react'

import { StandbyActions } from '../StandbyActions'
import { HomeIdentityMark, type HomeIdentityProps } from './HomeIdentity'

export type HomeStandbyProps = {
  identity: HomeIdentityProps
  actions: ComponentProps<typeof StandbyActions>
}

export function HomeStandby({ identity, actions }: HomeStandbyProps): ReactElement {
  return <section className="relative flex min-h-[28rem] w-full flex-1 flex-col items-center justify-center xl:min-h-0" aria-label="Standby">
    <div
      className="pointer-events-none absolute left-1/2 top-1/2 h-[380px] w-[380px] -translate-x-1/2 -translate-y-12 rounded-full opacity-10 mix-blend-screen blur-[120px]"
      style={{ background: 'rgba(var(--atmosphere-glow-color), 0.15)' }}
      aria-hidden
    />
    <HomeIdentityMark identity={identity} size="hero" />
    <div className="absolute inset-x-0 bottom-4 flex justify-center xl:bottom-8" data-slot="home-standby-actions">
      <StandbyActions {...actions} />
    </div>
  </section>
}
