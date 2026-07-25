import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AssistantToolCards } from './AssistantToolCards'

describe('AssistantToolCards MCP presentation', () => {
  it('shows provider, operation, success state, and compact structured output', () => {
    render(
      <AssistantToolCards
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
      <AssistantToolCards
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

    expect(screen.getByText(/brave brave news search — error/i)).toBeInTheDocument()
    expect(screen.getByText('Search provider is unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('Success')).not.toBeInTheDocument()
  })
})

describe('AssistantToolCards calendar presentation', () => {
  it('presents normalized all-day calendar events without shifting the date', () => {
    render(
      <AssistantToolCards
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
