import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReminderListRow } from './ReminderListRow'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ReminderListRow', () => {
  it('submits completion immediately when reduced motion disables the exit transition', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
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

  it('keeps the normal motion path tied to the opacity transition', async () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    const user = userEvent.setup()
    const onMarkRead = vi.fn()
    const { container } = render(
      <ReminderListRow
        reminder={{ id: 'local:7', note: 'Review notes', source: 'local', sync_state: 'pending' }}
        index={0}
        onMarkRead={onMarkRead}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Complete reminder local:7' }))
    expect(onMarkRead).not.toHaveBeenCalled()
    fireEvent.transitionEnd(container.querySelector('li')!, { propertyName: 'opacity' })
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
    const row = screen.getByRole('menu').closest('li')
    expect(row).toHaveClass('overflow-visible')
    expect(row).not.toHaveClass('overflow-hidden')
    await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
    expect(onEdit).toHaveBeenCalledWith('todo:task-1')
    await user.click(screen.getByRole('button', { name: 'Manage reminder todo:task-1' }))
    await user.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(onDelete).toHaveBeenCalledWith('todo:task-1')
  })
})
