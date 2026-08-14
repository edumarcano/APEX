import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { CompletedRemindersDialog } from './CompletedRemindersDialog'

const completedTask = {
  id: 'todo:done-1', title: 'Archive notes', importance: 'normal' as const,
  due: null, is_completed: true,
  completed_at: { date_time: '2026-08-14T09:00:00', time_zone: 'UTC' },
  last_modified_at: 'stamp-done',
}

describe('CompletedRemindersDialog', () => {
  it('loads completed tasks on open and removes a task only after verified reopen', async () => {
    const user = userEvent.setup()
    const onLoad = vi.fn().mockResolvedValue({ items: [completedTask], source_state: 'live' })
    const onReopen = vi.fn().mockResolvedValue({ id: completedTask.id, outcome: 'synced', action_id: 'action-1' })
    render(<CompletedRemindersDialog onClose={vi.fn()} onLoad={onLoad} onReopen={onReopen} />)

    expect(await screen.findByText('Archive notes')).toBeInTheDocument()
    expect(screen.getByText(/Completed 2026-08-14 09:00:00 \(UTC\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reopen' }))
    await waitFor(() => expect(onReopen).toHaveBeenCalledWith({ id: completedTask.id, last_modified_at: 'stamp-done' }))
    expect(screen.queryByText('Archive notes')).not.toBeInTheDocument()
  })

  it('shows unavailable state and retains uncertain tasks for review', async () => {
    const user = userEvent.setup()
    const onLoad = vi.fn().mockResolvedValueOnce({ items: [], source_state: 'unavailable' }).mockResolvedValueOnce({ items: [completedTask], source_state: 'live' })
    const onReopen = vi.fn().mockResolvedValue({ id: completedTask.id, outcome: 'unknown', action_id: 'action-uncertain' })
    render(<CompletedRemindersDialog onClose={vi.fn()} onLoad={onLoad} onReopen={onReopen} />)

    expect(await screen.findByText(/Completed reminders are unavailable/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Refresh completed reminders' }))
    expect(await screen.findByText('Archive notes')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(await screen.findByText(/action-uncertain/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reopen' })).toBeDisabled()
  })

  it('traps focus and restores the opener after Escape', async () => {
    const user = userEvent.setup()
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    let closeDialog = (): void => undefined
    const rendered = render(
      <CompletedRemindersDialog
        onClose={() => closeDialog()}
        onLoad={vi.fn().mockResolvedValue({ items: [], source_state: 'live' })}
        onReopen={vi.fn()}
      />,
    )
    closeDialog = rendered.unmount

    expect(await screen.findByRole('heading', { name: 'Completed reminders' })).toBeInTheDocument()
    expect(screen.getByRole('dialog') as HTMLElement).toContainElement(document.activeElement as HTMLElement)
    await user.keyboard('{Escape}')
    expect(opener).toHaveFocus()
    opener.remove()
  })
})
