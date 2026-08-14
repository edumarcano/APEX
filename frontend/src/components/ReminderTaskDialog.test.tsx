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
    const importance = screen.getByRole('combobox')
    expect(importance).toHaveClass('bg-zinc-950', '[color-scheme:dark]')
    expect(Array.from(importance.querySelectorAll('option'))).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ className: expect.stringContaining('bg-zinc-950') }),
      ]),
    )
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
})
