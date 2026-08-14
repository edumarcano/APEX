import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReminderListRow } from './ReminderListRow'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReminderListRow', () => {
  it('submits completion immediately without waiting for the exit transition', async () => {
    const user = userEvent.setup()
    const onMarkRead = vi.fn()

    render(
      <ReminderListRow
        reminder={{ id: 'todo:task-1', note: 'Review notes', source: 'todo', sync_state: 'synced' }}
        index={0}
        onMarkRead={onMarkRead}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Complete reminder todo:task-1' }))

    expect(onMarkRead).toHaveBeenCalledOnce()
    expect(onMarkRead).toHaveBeenCalledWith('todo:task-1')
  })

  it('does not require a transition event before submitting completion', async () => {
    const user = userEvent.setup()
    const onMarkRead = vi.fn()
    render(
      <ReminderListRow
        reminder={{ id: 'local:7', note: 'Review notes', source: 'local', sync_state: 'pending' }}
        index={0}
        onMarkRead={onMarkRead}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Complete reminder local:7' }))
    expect(onMarkRead).toHaveBeenCalledOnce()
    expect(onMarkRead).toHaveBeenCalledWith('local:7')
  })

  it('keeps completion visible while exposing edit and delete only for remote reminders', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    const onDelete = vi.fn()
    render(
      <ReminderListRow
        reminder={{ id: 'todo:task-1', note: 'Review notes', source: 'todo', sync_state: 'synced' }}
        index={0}
        onMarkRead={vi.fn()}
        onEdit={onEdit}
        onDelete={onDelete}
      />,
    )

    expect(screen.getByRole('button', { name: 'Complete reminder todo:task-1' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Manage reminder todo:task-1' }))
    await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
    expect(onEdit).toHaveBeenCalledWith('todo:task-1')
    await user.click(screen.getByRole('button', { name: 'Manage reminder todo:task-1' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(onDelete).toHaveBeenCalledWith('todo:task-1')
  })

  it('moves focus into the menu and restores it on Escape', async () => {
    const user = userEvent.setup()
    render(
      <ReminderListRow
        reminder={{ id: 'todo:task-1', note: 'Review notes', source: 'todo', sync_state: 'synced' }}
        index={0}
        onMarkRead={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Manage reminder todo:task-1' })
    await user.click(trigger)
    expect(screen.getByRole('menuitem', { name: 'Edit' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(trigger).toHaveFocus()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})
