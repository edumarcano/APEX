import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ActivityInboxWorkspace } from './ActivityInboxWorkspace'
import type { UseActivityInboxResult } from '../hooks/useActivityInbox'

const report = {
  id: 'report-1', partition: 'production' as const, client_id: 'codex', client_display_name: 'Codex', principal: 'operator', received_at: '2026-09-21T12:00:00Z', disposition: 'new' as const,
  report: { version: '1' as const, submission_key: 'key-1', title: 'External report', task_status: 'completed', outcome: 'Outside work completed.', findings: [{ title: 'Finding', text: 'Use the result.', derivation: 'unknown' as const }], evidence_links: ['javascript:alert(1)'], artifact_references: ['https://example.test/artifact'], unresolved_questions: [], suggested_follow_up: null, subjects: ['Project'], projects: [], occurred_at: null, native_task_url: 'javascript:alert(2)', markdown_body: '[unsafe](javascript:alert(3)) ![remote diagram](https://example.test/diagram.png) <script>bad()</script>' },
}

function inboxFixture(): UseActivityInboxResult {
  return {
    reports: [report], detail: report, linkedReviews: [], selectedReportId: report.id, sourceFilter: 'all', dispositionFilter: 'all', sources: [{ id: 'codex', label: 'Codex' }], isLoading: false, isDetailLoading: false, mutation: null, error: null,
    setSourceFilter: vi.fn(), setDispositionFilter: vi.fn(), selectReport: vi.fn(), refresh: vi.fn().mockResolvedValue(undefined), setDisposition: vi.fn().mockResolvedValue(true), proposeContext: vi.fn().mockResolvedValue(null),
  }
}

describe('ActivityInboxWorkspace', () => {
  it('keeps unsafe external locations inert and supports keyboard disposition controls', async () => {
    const user = userEvent.setup()
    const inbox = inboxFixture()
    render(<ActivityInboxWorkspace inbox={inbox} demoModeActive={false} sandboxMode={false} onOpenReview={vi.fn().mockResolvedValue(null)} />)

    const workspace = screen.getByRole('region', { name: 'External activity inbox' })
    expect(workspace).toHaveClass('min-h-0')
    expect(workspace).toHaveClass('w-full', 'mx-auto')
    expect(workspace).not.toHaveClass('max-w-[1520px]')
    expect(workspace.querySelector('svg')?.parentElement).toHaveClass('text-[#FFD166]')
    expect(screen.getByRole('complementary', { name: 'Activity reports' })).toHaveClass('scrollbar-thin')
    expect(screen.getByRole('article')).toHaveClass('lg:overflow-y-auto')
    expect(screen.getByRole('article')).toHaveClass('scrollbar-thin')
    expect(document.querySelector('script')).toBeNull()
    expect(document.querySelector('img')).toBeNull()
    expect(screen.queryByRole('link', { name: 'unsafe' })).not.toBeInTheDocument()
    expect(screen.getByText('Image omitted: remote diagram')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /https:\/\/example.test\/artifact/i })).toHaveAttribute('href', 'https://example.test/artifact')

    screen.getByRole('button', { name: 'reviewed' }).focus()
    await user.keyboard('{Enter}')
    expect(inbox.setDisposition).toHaveBeenCalledWith('reviewed')
  })

  it('shows a mailbox scan error without replacing reports already in the Inbox', () => {
    const inbox = { ...inboxFixture(), error: 'The mailbox folder is unavailable; APEX will retry.' }
    render(<ActivityInboxWorkspace inbox={inbox} demoModeActive={false} sandboxMode={false} onOpenReview={vi.fn().mockResolvedValue(null)} />)

    expect(screen.getByRole('alert')).toHaveTextContent('The mailbox folder is unavailable; APEX will retry.')
    expect(screen.getByRole('button', { name: /External report/ })).toBeInTheDocument()
  })
})
