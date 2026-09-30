import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { PreflightDialog } from './PreflightDialog'

describe('PreflightDialog', () => {
  it('offers continue once, continue for session, and cancel for warnings', async () => {
    const onChoice = vi.fn()
    const user = userEvent.setup()
    render(
      <PreflightDialog
        open
        operation="activate"
        warnings={[{ code: 'running_on_battery', message: 'Running on battery' }]}
        blockers={[]}
        isChecking={false}
        error={null}
        onChoice={onChoice}
      />,
    )

    expect(screen.getByRole('dialog')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /continue once/i }))
    expect(onChoice).toHaveBeenCalledWith('continue_once')
  })

  it('blocks with close only when blockers are present', async () => {
    const onChoice = vi.fn()
    const user = userEvent.setup()
    render(
      <PreflightDialog
        open
        operation="activate"
        warnings={[]}
        blockers={[{ code: 'missing_credentials', message: 'Missing credentials' }]}
        isChecking={false}
        error={null}
        onChoice={onChoice}
      />,
    )

    expect(screen.queryByRole('button', { name: /continue once/i })).toBeNull()
    await user.click(screen.getByRole('button', { name: /^close$/i }))
    expect(onChoice).toHaveBeenCalledWith('cancel')
  })

  it('traps keyboard focus inside the dialog and restores it after close', async () => {
    const onChoice = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(
      <>
        <button type="button">Open preflight</button>
        <PreflightDialog
          open={false}
          operation={null}
          warnings={[]}
          blockers={[]}
          isChecking={false}
          error={null}
          onChoice={onChoice}
        />
      </>,
    )
    const trigger = screen.getByRole('button', { name: 'Open preflight' })
    trigger.focus()

    rerender(
      <>
        <button type="button">Open preflight</button>
        <PreflightDialog
          open
          operation="activate"
          warnings={[{ code: 'running_on_battery', message: 'Running on battery' }]}
          blockers={[]}
          isChecking={false}
          error={null}
          onChoice={onChoice}
        />
      </>,
    )

    expect(screen.getByRole('button', { name: 'Close preflight dialog' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: /continue for this session/i })).toHaveFocus()

    rerender(
      <>
        <button type="button">Open preflight</button>
        <PreflightDialog
          open={false}
          operation={null}
          warnings={[]}
          blockers={[]}
          isChecking={false}
          error={null}
          onChoice={onChoice}
        />
      </>,
    )
    expect(screen.getByRole('button', { name: 'Open preflight' })).toHaveFocus()
  })
})
