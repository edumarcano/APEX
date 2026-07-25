import { describe, expect, it } from 'vitest'

import { OPERATION_PROMPT_CHIPS } from './promptChips'

describe('operation prompt chips', () => {
  it('requests the assistant calendar tool fourteen-day horizon', () => {
    const schedule = OPERATION_PROMPT_CHIPS.find(
      (chip) => chip.label === 'Schedule',
    )

    expect(schedule?.query).toBe(
      'Show my calendar events for the next fourteen days.',
    )
  })
})
