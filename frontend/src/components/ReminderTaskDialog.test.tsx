import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ReminderTaskDialog } from './ReminderTaskDialog'

const task = {
  id: 'todo:task-1', title: 'Review plan', importance: 'high' as const,
  due: { date_time: '2026-08-15T09:30:00', time_zone: 'Eastern Standard Time' },
  is_completed: false, completed_at: null, last_modified_at: 'stamp-1',
}

describe('ReminderTaskDialog', () => {
  it('submits only changed fields and clears an existing due date explicitly', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockResolvedValue({ id: task.id, outcome: 'synced', action_id: 'action-1' })
    const onClose = vi.fn()
    render(<ReminderTaskDialog id={task.id} mode="edit" onClose={onClose} onLoad={vi.fn().mockResolvedValue(task)} onUpdate={onUpdate} onDelete={vi.fn()} />)

    await screen.findByDisplayValue('Review plan')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: 'Include due date' }))
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith({
      id: task.id, last_modified_at: 'stamp-1', due: null,
    }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('keeps the dialog open when the verified action outcome is uncertain', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockResolvedValue({ id: task.id, outcome: 'unknown', action_id: 'action-uncertain' })
    render(<ReminderTaskDialog id={task.id} mode="edit" onClose={vi.fn()} onLoad={vi.fn().mockResolvedValue(task)} onUpdate={onUpdate} onDelete={vi.fn()} />)

    const title = await screen.findByDisplayValue('Review plan')
    await user.clear(title)
    await user.type(title, 'Review revised plan')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText(/action-uncertain/)).toBeInTheDocument()
  })

  it('requires an explicit delete confirmation after loading the exact task', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn().mockResolvedValue({ id: task.id, outcome: 'synced', action_id: 'action-delete' })
    const onClose = vi.fn()
    render(<ReminderTaskDialog id={task.id} mode="delete" onClose={onClose} onLoad={vi.fn().mockResolvedValue(task)} onUpdate={vi.fn()} onDelete={onDelete} />)

    expect(await screen.findByText('Review plan')).toBeInTheDocument()
    expect(onDelete).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Delete task' }))
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith({ id: task.id, last_modified_at: 'stamp-1' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('traps focus and restores the opener after Escape', async () => {
    const user = userEvent.setup()
    const opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    let closeDialog = (): void => undefined
    const rendered = render(
      <ReminderTaskDialog
        id={task.id}
        mode="edit"
        onClose={() => closeDialog()}
        onLoad={vi.fn().mockResolvedValue(task)}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />,
    )
    closeDialog = rendered.unmount

    await screen.findByDisplayValue('Review plan')
    expect(screen.getByRole('dialog') as HTMLElement).toContainElement(document.activeElement as HTMLElement)
    await user.keyboard('{Escape}')
    expect(opener).toHaveFocus()
    opener.remove()
  })
})
