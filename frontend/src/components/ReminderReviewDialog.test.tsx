import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ReminderReviewDialog } from './ReminderReviewDialog'

describe('ReminderReviewDialog', () => {
  it('removes selections that are no longer pending after a refresh', async () => {
    const props = {
      onClose: vi.fn(),
      onSync: vi.fn().mockResolvedValue([]),
      onDismissUnknown: vi.fn().mockResolvedValue(undefined),
    }
    const { rerender } = render(
      <ReminderReviewDialog
        {...props}
        reminders={[{ id: 'local:7', note: 'Review notes', source: 'local', sync_state: 'pending' }]}
      />,
    )

    expect(screen.getByRole('button', { name: 'Sync selected' })).toBeEnabled()

    rerender(<ReminderReviewDialog {...props} reminders={[]} />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Sync selected' })).toBeDisabled()
    })
  })
})
