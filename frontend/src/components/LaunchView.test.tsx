import { createRef } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { LaunchView } from './LaunchView'

function renderLaunch(current: 'overview' | 'briefing' | 'cortex' | 'reports' | null = null, onSelect = vi.fn(), onOpenSettings = vi.fn()) {
  return {
    onSelect,
    onOpenSettings,
    ...render(<LaunchView
    logoProps={{ status: 'idle' }}
    current={current}
    onSelect={onSelect}
    onOpenSettings={onOpenSettings}
    settingsButtonRef={createRef<HTMLButtonElement>()}
    mode={null}
    />),
  }
}

const WORKSPACES: Array<[string, string, string]> = [
  ['Overview', 'overview', 'text-[#1F6FE5]'],
  ['Briefing', 'briefing', 'text-[#FBBF24]'],
  ['Cortex', 'cortex', 'text-[#D8B4FE]'],
  ['Reports', 'reports', 'text-slate-300'],
]

describe('LaunchView', () => {
  it('offers each workspace once and routes its accessible button', () => {
    const onSelect = vi.fn()
    renderLaunch(null, onSelect)
    const workspace = screen.getByRole('navigation', { name: 'Workspace' })
    const buttons = within(workspace).getAllByRole('button')
    expect(buttons.map((button) => button.textContent?.trim())).toEqual(WORKSPACES.map(([label]) => label))
    for (const [label] of WORKSPACES) {
      const button = within(workspace).getByRole('button', { name: label })
      fireEvent.click(button)
      expect(onSelect).toHaveBeenLastCalledWith(label.toLowerCase())
    }
  })

  it('marks the current workspace and keeps the documented neutral surfaces and peer icon accents', () => {
    renderLaunch('briefing')
    for (const [label, id, iconClass] of WORKSPACES) {
      const button = screen.getByRole('button', { name: label })
      if (label === 'Briefing') expect(button).toHaveAttribute('aria-current', 'page')
      else expect(button).not.toHaveAttribute('aria-current')
      expect(button).toHaveClass('hud-glass', 'text-zinc-300', 'border-white/10')
      const icon = screen.getByTestId(`launch-icon-${id}`)
      expect(icon).toHaveClass(iconClass)
    }
    const settings = screen.getByRole('button', { name: 'Open settings' })
    expect(settings).toHaveClass('hud-glass', 'text-zinc-300')
    expect(settings.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('shows the APEX identity and opens Settings on request', () => {
    const onOpenSettings = vi.fn()
    renderLaunch(null, vi.fn(), onOpenSettings)
    expect(screen.getByRole('heading', { name: 'APEX' })).toHaveClass('text-[#FBBF24]')
    const wrapper = screen.getByTestId('launch-logo')
    expect(wrapper.querySelector('svg')).toBeInTheDocument()
    expect(wrapper.className).toContain('hover:drop-shadow')
    fireEvent.click(screen.getByRole('button', { name: 'Open settings' }))
    expect(onOpenSettings).toHaveBeenCalledOnce()
  })
})
