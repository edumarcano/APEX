import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { HudIdentityMark, type HudIdentityProps } from './HudIdentity'

const identity: HudIdentityProps = {
  logoProps: { status: 'idle' },
  glyphProps: { status: 'idle', isSpeaking: false },
}

function renderMark(size: 'hero' | 'large' | 'overview' | 'compact') {
  const { container } = render(<HudIdentityMark identity={identity} size={size} />)
  const root = container.querySelector('[data-slot="home-identity"]') as HTMLElement
  const glow = root.firstElementChild as HTMLElement
  const logo = glow.firstElementChild as HTMLElement
  return { root, glow, logo }
}

describe('HudIdentityMark', () => {
  it.each(['hero', 'overview'] as const)('exposes size and hover glow for %s', (size) => {
    const { root, glow, logo } = renderMark(size)
    expect(root.getAttribute('data-logo-size')).toBe(size)
    expect(glow.className).toContain('hover:drop-shadow')
    expect(logo.className).toContain('duration-700')
    expect(logo.className).toContain('motion-reduce:transition-none')
  })

  it('keeps hero scale and overview sizing without the hero height cap', () => {
    expect(renderMark('hero').glow.className).toContain('scale-115')
    const { logo } = renderMark('overview')
    expect(logo.className).toContain('h-24')
    expect(logo.className).not.toContain('hud-logo-mark')
  })
})
