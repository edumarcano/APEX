import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ReminderQuickAdd } from './ReminderQuickAdd'

describe('ReminderQuickAdd', () => {
  it('opens from the header action and reports a queued save', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue('pending')
    render(<ReminderQuickAdd onSave={onSave} />)

    const trigger = screen.getByRole('button', { name: 'Add reminder' })
    await user.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Add reminder' })).toBeVisible()

    await user.type(screen.getByRole('textbox', { name: 'Reminder text' }), 'Call the dentist')
    await user.click(screen.getByRole('button', { name: 'Save reminder' }))

    await waitFor(() => expect(onSave).toHaveBeenCalledWith('Call the dentist'))
    expect(screen.getByText('Queued locally for review.')).toBeVisible()
    expect(screen.getByRole('dialog', { name: 'Add reminder' })).toBeVisible()
  })

  it('keeps the popover open and reports a save failure', async () => {
    const user = userEvent.setup()
    const onSave = vi.fn().mockRejectedValue(new Error('offline'))
    render(<ReminderQuickAdd onSave={onSave} />)

    await user.click(screen.getByRole('button', { name: 'Add reminder' }))
    await user.type(screen.getByRole('textbox', { name: 'Reminder text' }), 'Review notes')
    await user.click(screen.getByRole('button', { name: 'Save reminder' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save reminder. Try again.')
    expect(screen.getByRole('dialog', { name: 'Add reminder' })).toBeVisible()
  })

  it('dismisses with Escape and restores focus to the header action', async () => {
    const user = userEvent.setup()
    render(<ReminderQuickAdd onSave={vi.fn(async (): Promise<'pending'> => 'pending')} />)

    const trigger = screen.getByRole('button', { name: 'Add reminder' })
    await user.click(trigger)
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog', { name: 'Add reminder' })).toBeNull()
    expect(trigger).toHaveFocus()
  })
})
