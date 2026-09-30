import { useRef, useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { DeferredSettingsPanel } from './DeferredSettingsPanel'

vi.mock('./SettingsPanel', () => ({
  default: () => { throw new Error('settings component failed') },
}))

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

describe('DeferredSettingsPanel load error', () => {
  it('offers retry and asks before reloading with unsent text loss explained', async () => {
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Open settings' })
    trigger.focus()
    await user.click(trigger)

    expect(await screen.findByRole('alert')).toHaveTextContent(/settings panel failed to load/i)
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Retry' })).toHaveFocus()
    const reload = screen.getByRole('button', { name: 'Reload APEX' })
    await user.click(reload)
    expect(confirm).toHaveBeenCalledWith('Reload APEX? Reloading will discard unsent text.')
    expect(reload).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload APEX' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
