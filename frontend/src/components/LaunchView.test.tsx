import { createRef } from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { LaunchView } from './LaunchView'

function renderLaunch() {
  return render(<LaunchView
    logoProps={{ step: null, status: 'idle' }}
    current={null}
    onSelect={vi.fn()}
    onOpenSettings={vi.fn()}
    settingsButtonRef={createRef<HTMLButtonElement>()}
    mode={null}
  />)
}

const ICON_ACCENTS: Array<[string, string, string]> = [
  ['Reports', 'reports', '#22D3EE'],
  ['Overview', 'overview', '#1F6FE5'],
  ['Briefing', 'briefing', '#FBBF24'],
  ['Cortex', 'cortex', '#D8B4FE'],
]

describe('LaunchView', () => {
  it('keeps workspace buttons neutral with accent icons only', () => {
    renderLaunch()
    for (const [label, id, iconColor] of ICON_ACCENTS) {
      const button = screen.getByRole('button', { name: label })
      expect(button).toHaveClass('hud-glass', 'text-zinc-300', 'border-white/10')
      expect(button.className).not.toMatch(/(?:^|\s)bg-\[#(?:22D3EE|0F4DB8|FBBF24|7E22CE)\]\/\d+/)
      expect(button.className).not.toMatch(/(?:^|\s)text-\[#(?:22D3EE|1F6FE5|0F4DB8|A5C7FF|FBBF24|D8B4FE|A5F3FC|FFF3B0)\]/)
      const icon = screen.getByTestId(`launch-icon-${id}`)
      expect(icon).toHaveClass(`text-[${iconColor}]`)
    }
  })

  it('keeps settings off the workspace accent colors', () => {
    renderLaunch()
    const settings = screen.getByRole('button', { name: 'Open settings' })
    for (const [, , iconColor] of ICON_ACCENTS) expect(settings).not.toHaveClass(`text-[${iconColor}]`)
  })

  it('renders the hero wordmark and logo', () => {
    renderLaunch()
    expect(screen.getByRole('heading', { name: 'APEX' })).toHaveClass('text-[#FBBF24]', 'text-3xl', 'sm:text-4xl', 'xl:text-5xl')
    const wrapper = screen.getByTestId('launch-logo')
    expect(wrapper).not.toHaveClass('scale-115')
    expect(wrapper.className).toContain('hover:drop-shadow')
    const logo = wrapper.querySelector('.hud-logo-mark')
    expect(logo).toHaveClass('h-56', 'sm:h-64', 'xl:h-80')
  })
})
