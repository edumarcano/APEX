import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CortexToolCards } from './CortexToolCards'

describe('CortexToolCards MCP presentation', () => {
  it('shows provider, operation, success state, and compact structured output', () => {
    render(
      <CortexToolCards
        toolOutputs={[
          {
            name: 'brave_brave_web_search',
            status: 'ok',
            duration_ms: 18.4,
            output: {
              results: [{ title: 'FastMCP documentation', url: 'https://example.test' }],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Brave Search')).toBeInTheDocument()
    expect(screen.getByText('web search')).toBeInTheDocument()
    expect(screen.getByText('Success')).toBeInTheDocument()
    expect(screen.getByText(/FastMCP documentation/)).toBeInTheDocument()
  })

  it('uses the masked error card for a failed MCP operation', () => {
    render(
      <CortexToolCards
        toolOutputs={[
          {
            name: 'brave_brave_news_search',
            status: 'error',
            duration_ms: 7,
            output: { error: 'Search provider is unavailable.' },
          },
        ]}
      />,
    )

    expect(screen.getByText(/brave brave news search/i)).toBeInTheDocument()
    expect(screen.getByText('Search provider is unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('Success')).not.toBeInTheDocument()
  })
})

describe('CortexToolCards calendar presentation', () => {
  it('presents normalized all-day calendar events without shifting the date', () => {
    render(
      <CortexToolCards
        toolOutputs={[
          {
            name: 'get_upcoming_calendar_events',
            status: 'ok',
            duration_ms: 12,
            output: {
              days_queried: 14,
              events: [
                {
                  summary: 'Conference',
                  start: '2026-07-26',
                  end: '2026-07-27',
                  all_day: true,
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Next 14 days')).toBeInTheDocument()
    expect(screen.getByText('Conference')).toBeInTheDocument()
    expect(screen.getByText(/Jul 26 · All day/)).toBeInTheDocument()
  })
})

describe('CortexToolCards Gmail presentation', () => {
  it('renders bounded Gmail search metadata in a dedicated result list', () => {
    render(
      <CortexToolCards
        toolOutputs={[
          {
            name: 'search_gmail',
            status: 'ok',
            duration_ms: 21,
            output: {
              query: 'from:travel@example.com newer_than:30d',
              result_count: 1,
              messages: [
                {
                  id: 'message-1',
                  thread_id: 'thread-1',
                  sender: 'Travel Desk <travel@example.com>',
                  subject: 'Flight confirmation',
                  date: 'Mon, 27 Jul 2026 09:30:00 -0400',
                  labels: ['INBOX', 'IMPORTANT'],
                  snippet: 'Your flight is confirmed for Wednesday.',
                },
              ],
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Gmail Search')).toBeInTheDocument()
    expect(
      screen.getByText('from:travel@example.com newer_than:30d'),
    ).toBeInTheDocument()
    expect(screen.getByText('1 result')).toBeInTheDocument()
    expect(screen.getByText('Flight confirmation')).toBeInTheDocument()
    expect(
      screen.getByText('Travel Desk <travel@example.com>'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Your flight is confirmed for Wednesday.'),
    ).toBeInTheDocument()
    expect(screen.getByText('IMPORTANT')).toBeInTheDocument()
  })

  it('renders a selected message as inert plain text and marks truncation', () => {
    const { container } = render(
      <CortexToolCards
        toolOutputs={[
          {
            name: 'get_gmail_message',
            status: 'ok',
            duration_ms: 17,
            output: {
              id: 'message-2',
              thread_id: 'thread-2',
              sender: 'Reports <reports@example.com>',
              subject: 'Quarterly report',
              date: 'Mon, 27 Jul 2026 10:15:00 -0400',
              labels: ['INBOX'],
              snippet: 'Report preview',
              body: '<img src=x onerror=alert(1)> Plain report text',
              truncated: true,
            },
          },
        ]}
      />,
    )

    expect(screen.getByText('Gmail Message')).toBeInTheDocument()
    expect(screen.getByText('Quarterly report')).toBeInTheDocument()
    expect(
      screen.getByText('<img src=x onerror=alert(1)> Plain report text'),
    ).toBeInTheDocument()
    expect(screen.getByText('Message text truncated')).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
  })
})
