import { useRef, useState, type ComponentProps } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type SettingsPanel from './SettingsPanel'
import { DeferredSettingsPanel } from './DeferredSettingsPanel'

type SettingsModule = typeof import('./SettingsPanel')

const settingsModule = vi.hoisted(() => {
  let resolve!: (module: SettingsModule) => void
  const promise = new Promise<SettingsModule>((done) => { resolve = done })
  return { promise, resolve: (module: SettingsModule) => resolve(module) }
})

vi.mock('./SettingsPanel', () => settingsModule.promise)

function Harness() {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  return <>
    <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>Open settings</button>
    <DeferredSettingsPanel
      open={open}
      onClose={() => setOpen(false)}
      restoreFocusRef={triggerRef}
      briefingRunning={false}
      briefingStep={null}
      isSpeaking={false}
      isCortexQuerying={false}
      modelCatalog={[]}
      cortexAgentHydrated
      failedConnectors={[]}
      hasTelemetryEvidence={false}
      onApplied={() => undefined}
    />
  </>
}

describe('DeferredSettingsPanel loading lifecycle', () => {
  it('closes while loading and stays closed when the module resolves later', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Open settings' })
    trigger.focus()
    await user.click(trigger)

    expect(screen.getByRole('dialog', { name: 'Loading settings' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()

    settingsModule.resolve({
      default: ({ open }: Pick<ComponentProps<typeof SettingsPanel>, 'open'>) => open ? <div role="dialog" aria-label="Loaded settings">Loaded</div> : <output data-testid="settings-loaded-closed" />,
    } as SettingsModule)

    expect(await screen.findByTestId('settings-loaded-closed')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
