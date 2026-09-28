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

const ACCENTS: Array<[string, string, string]> = [
  ['Reports', '#22D3EE', '#A5F3FC'],
  ['Overview', '#0F4DB8', '#A5C7FF'],
  ['Briefing', '#FBBF24', '#FFF3B0'],
  ['Cortex', '#7E22CE', '#D8B4FE'],
]

describe('LaunchView', () => {
  it('shows each workspace accent at rest', () => {
    renderLaunch()
    for (const [label, fill, text] of ACCENTS) {
      const button = screen.getByRole('button', { name: label })
      expect(button).toHaveClass(`text-[${text}]`)
      expect(button.className).toMatch(new RegExp(`(^|\\s)bg-\\[${fill}\\]/\\d+`))
      expect(button.className).toMatch(new RegExp(`(^|\\s)border-\\[${fill}\\]/\\d+`))
      expect(button).not.toHaveClass('hud-glass')
    }
  })

  it('keeps settings off the workspace accent colors', () => {
    renderLaunch()
    const settings = screen.getByRole('button', { name: 'Open settings' })
    for (const [, , text] of ACCENTS) expect(settings).not.toHaveClass(`text-[${text}]`)
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
