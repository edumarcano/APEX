import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ActivityReportsWorkspace } from './ActivityReportsWorkspace'
import type { UseActivityReportsResult } from '../hooks/useActivityReports'

const report = {
  id: 'report-1', partition: 'production' as const, client_id: 'codex', client_display_name: 'Codex', principal: 'operator', received_at: '2026-09-21T12:00:00Z', disposition: 'new' as const,
  report: { version: '1' as const, submission_key: 'key-1', title: 'External report', task_status: 'completed', outcome: 'Outside work completed.', findings: [{ title: 'Finding', text: 'Use the result.', derivation: 'unknown' as const }], evidence_links: ['javascript:alert(1)'], artifact_references: ['https://example.test/artifact'], unresolved_questions: [], suggested_follow_up: null, subjects: ['Project'], projects: [], occurred_at: null, native_task_url: 'javascript:alert(2)', markdown_body: '[unsafe](javascript:alert(3)) ![remote diagram](https://example.test/diagram.png) <script>bad()</script>' },
}

function reportsFixture(): UseActivityReportsResult {
  return {
    reports: [report], detail: report, linkedReviews: [], selectedReportId: report.id, sourceFilter: 'all', dispositionFilter: 'all', sources: [{ id: 'codex', label: 'codex' }], isLoading: false, isDetailLoading: false, mutation: null, error: null,
    setSourceFilter: vi.fn(), setDispositionFilter: vi.fn(), selectReport: vi.fn(), refresh: vi.fn().mockResolvedValue(undefined), setDisposition: vi.fn().mockResolvedValue(true), proposeContext: vi.fn().mockResolvedValue(null),
  }
}

describe('ActivityReportsWorkspace', () => {
  it('keeps unsafe external locations inert and supports keyboard disposition controls', async () => {
    const user = userEvent.setup()
    const reports = reportsFixture()
    render(<ActivityReportsWorkspace reports={reports} demoModeActive={false} sandboxMode={false} onOpenReview={vi.fn().mockResolvedValue(null)} />)

    const workspace = screen.getByRole('region', { name: 'External activity reports' })
    expect(workspace).toHaveClass('min-h-0')
    expect(workspace).toHaveClass('w-full', 'mx-auto')
    expect(workspace).not.toHaveClass('max-w-[1520px]')
    expect(workspace.querySelector('svg')?.parentElement).toHaveClass('text-slate-200')
    expect(screen.getByRole('complementary', { name: 'Activity reports' })).toHaveClass('scrollbar-thin')
    expect(screen.getByRole('article')).toHaveClass('lg:overflow-y-auto')
    expect(screen.getByRole('article')).toHaveClass('scrollbar-thin')
    expect(screen.getAllByText('Codex · completed')).toHaveLength(2)
    expect(screen.getByRole('option', { name: 'codex' })).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    expect(document.querySelector('img')).toBeNull()
    expect(screen.queryByRole('link', { name: 'unsafe' })).not.toBeInTheDocument()
    expect(screen.getByText('Image omitted: remote diagram')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /https:\/\/example.test\/artifact/i })).toHaveAttribute('href', 'https://example.test/artifact')

    screen.getByRole('button', { name: 'reviewed' }).focus()
    await user.keyboard('{Enter}')
    expect(reports.setDisposition).toHaveBeenCalledWith('reviewed')
  })

  it('shows a report folder scan error without replacing reports already in Reports', () => {
    const reports = { ...reportsFixture(), error: 'The report folder is unavailable; APEX will retry.' }
    render(<ActivityReportsWorkspace reports={reports} demoModeActive={false} sandboxMode={false} onOpenReview={vi.fn().mockResolvedValue(null)} />)

    expect(screen.getByRole('alert')).toHaveTextContent('The report folder is unavailable; APEX will retry.')
    expect(screen.getByRole('button', { name: /External report/ })).toBeInTheDocument()
  })

  it('preserves the draft across same-report refreshes and resets it for a newly selected report', async () => {
    const user = userEvent.setup()
    const reports = reportsFixture()
    const onOpenReview = vi.fn().mockResolvedValue(null)
    const { rerender } = render(<ActivityReportsWorkspace reports={reports} demoModeActive={false} sandboxMode={false} onOpenReview={onOpenReview} />)

    const text = screen.getByLabelText('Proposed context')
    await user.clear(text)
    await user.type(text, 'My edited context')
    await user.click(screen.getByText('Structured context fields'))
    await user.type(screen.getByLabelText('Subject'), 'Edited subject')

    const refreshedReport = {
      ...report,
      disposition: 'reviewed' as const,
      received_at: '2026-09-22T12:00:00Z',
      report: { ...report.report },
    }
    const refreshedReports = { ...reports, reports: [refreshedReport], detail: refreshedReport }
    rerender(<ActivityReportsWorkspace reports={refreshedReports} demoModeActive={false} sandboxMode={false} onOpenReview={onOpenReview} />)

    expect(screen.getByLabelText('Proposed context')).toHaveValue('My edited context')
    expect(screen.getByLabelText('Subject')).toHaveValue('Edited subject')

    const nextReport = {
      ...report,
      id: 'report-2',
      received_at: '2026-09-23T12:00:00Z',
      report: {
        ...report.report,
        title: 'Next report',
        findings: [{ title: 'New finding', text: 'Evidence from the next report.', derivation: 'unknown' as const }],
      },
    }
    const nextReports = {
      ...refreshedReports,
      reports: [refreshedReport, nextReport],
      detail: nextReport,
      selectedReportId: nextReport.id,
    }
    rerender(<ActivityReportsWorkspace reports={nextReports} demoModeActive={false} sandboxMode={false} onOpenReview={onOpenReview} />)

    expect(screen.getByLabelText('Proposed context')).toHaveValue('Evidence from the next report.')
    expect(screen.getByLabelText('Subject')).toHaveValue('')
  })

  it('replaces the text and clears structured fields when the operator selects another finding', async () => {
    const user = userEvent.setup()
    const twoFindingReport = {
      ...report,
      report: {
        ...report.report,
        findings: [
          ...report.report.findings,
          { title: 'Second finding', text: 'Second evidence statement.', derivation: 'unknown' as const },
        ],
      },
    }
    const reports = { ...reportsFixture(), reports: [twoFindingReport], detail: twoFindingReport }
    render(<ActivityReportsWorkspace reports={reports} demoModeActive={false} sandboxMode={false} onOpenReview={vi.fn().mockResolvedValue(null)} />)

    await user.click(screen.getByText('Structured context fields'))
    await user.type(screen.getByLabelText('Subject'), 'First finding subject')
    await user.selectOptions(screen.getByLabelText('Finding'), '/findings/1')

    expect(screen.getByLabelText('Proposed context')).toHaveValue('Second evidence statement.')
    expect(screen.getByLabelText('Subject')).toHaveValue('')
  })
})
