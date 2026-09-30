import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { HudIdentityMark, type HudIdentityProps } from './HudIdentity'

const identity: HudIdentityProps = {
  logoProps: { status: 'idle' },
  glyphProps: { status: 'idle', isSpeaking: false },
}

describe('HudIdentityMark', () => {
  it('keeps the active signal label and reduced-motion mark transition across hero and overview', () => {
    const activeIdentity: HudIdentityProps = {
      ...identity,
      glyphProps: { ...identity.glyphProps, activity: 'briefing_ready' },
    }
    const { container, rerender } = render(<HudIdentityMark identity={activeIdentity} size="hero" />)
    for (const size of ['hero', 'overview'] as const) {
      if (size === 'overview') rerender(<HudIdentityMark identity={activeIdentity} size={size} />)
      const glyph = container.querySelector('[data-slot="voice-signal-glyph"]')
      const logo = container.querySelector('[data-activity="briefing_ready"]')
      expect(glyph).toHaveAttribute('data-signal-tone', 'gold')
      expect(glyph).toHaveTextContent('Briefing ready')
      expect(logo).toHaveClass('motion-reduce:transition-none')
    }
  })

  it('keeps the sidebar signal label aligned with the current Cortex activity', () => {
    const sidebarIdentity: HudIdentityProps = {
      ...identity,
      glyphProps: { ...identity.glyphProps, isCortexQuerying: true, cortexActivityLabel: 'Checking your calendar' },
    }
    const { container } = render(<HudIdentityMark identity={sidebarIdentity} size="sidebar" />)
    expect(container.querySelector('[data-slot="voice-signal-glyph"]')).toHaveTextContent('Checking your calendar')
  })

  it('passes hideLabel to the nested voice signal glyph', () => {
    const { container } = render(<HudIdentityMark identity={identity} size="large" hideLabel />)
    const glyph = container.querySelector('[data-slot="voice-signal-glyph"]')
    expect(glyph).toBeInTheDocument()
    expect(glyph?.textContent?.trim()).toBe('')
  })
})
