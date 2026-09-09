import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import CalendarSettingsSection from './CalendarSettingsSection'

afterEach(() => vi.unstubAllGlobals())

describe('CalendarSettingsSection', () => {
  it('loads choices once, preserves unavailable saved IDs, and updates selection', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      calendars: [{ id: 'primary', display_name: 'Personal', primary: true, hidden: false }],
      truncated: false,
    })))
    vi.stubGlobal('fetch', fetchMock)
    const onChange = vi.fn()

    render(
      <CalendarSettingsSection
        sectionId="calendar"
        enabled
        settings={{ selected_calendar_ids: ['primary', 'missing'], show_calendar_names: true }}
        timing="Active"
        onChange={onChange}
      />,
    )

    expect(await screen.findByText('Personal · Primary')).toBeInTheDocument()
    expect(screen.getByText('Saved calendar unavailable')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: /Saved calendar unavailable/i }))
    expect(onChange).toHaveBeenCalledWith({ selected_calendar_ids: ['primary'], show_calendar_names: true })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
  })

  it('offers a retry after discovery fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ calendars: [], truncated: false })))
    vi.stubGlobal('fetch', fetchMock)

    render(<CalendarSettingsSection sectionId="calendar" enabled settings={{ selected_calendar_ids: [], show_calendar_names: true }} timing="Active" onChange={vi.fn()} />)

    expect(await screen.findByText(/Calendar choices are unavailable/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })

  it('blocks a twenty-sixth selection while allowing selected calendars to be removed', async () => {
    const choices = Array.from({ length: 26 }, (_, index) => ({
      id: `calendar-${index + 1}`,
      display_name: `Calendar ${index + 1}`,
      primary: false,
      hidden: false,
    }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ calendars: choices, truncated: false }))))
    const onChange = vi.fn()

    render(
      <CalendarSettingsSection
        sectionId="calendar"
        enabled
        settings={{ selected_calendar_ids: choices.slice(0, 25).map((choice) => choice.id), show_calendar_names: true }}
        timing="Active"
        onChange={onChange}
      />,
    )

    const unavailableChoice = await screen.findByRole('checkbox', { name: 'Calendar 26' })
    expect(unavailableChoice).toBeDisabled()
    expect(screen.getByText('25 of 25 calendars selected. Select up to 25; remove a selected calendar before adding another.')).toBeInTheDocument()
    fireEvent.click(unavailableChoice)
    expect(onChange).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('checkbox', { name: 'Calendar 1' }))
    expect(onChange).toHaveBeenCalledWith({
      selected_calendar_ids: choices.slice(1, 25).map((choice) => choice.id),
      show_calendar_names: true,
    })
  })
})
