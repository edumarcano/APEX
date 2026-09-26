import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { ToolOutputItem } from '../../types/telemetry'
import { CompactToolResults } from './CompactToolResults'

const approval: ToolOutputItem = {
  name: 'propose_action',
  status: 'ok',
  duration_ms: 4,
  output: { action_id: 'action-1', status: 'proposed', version: 0, risk: 'write', summary: 'Remember tea preference', target: 'Personal context' },
}
const failure: ToolOutputItem = { name: 'search_gmail', status: 'error', duration_ms: 3, output: { error: 'Gmail is unavailable right now.' } }
const trustLabelled: ToolOutputItem = {
  name: 'search_apex_docs',
  status: 'ok',
  duration_ms: 2,
  output: { retrieval_mode: 'lexical', trust: 'reference', results: [] },
}
const routine: ToolOutputItem = { name: 'brave_web_search', status: 'ok', duration_ms: 5, output: 'Routine search payload' }

describe('CompactToolResults', () => {
  it('always renders approvals, failures, and trust-labelled results in full', () => {
    render(<CompactToolResults toolOutputs={[routine, approval, failure, trustLabelled]} />)

    expect(screen.getByText('Remember tea preference')).toBeInTheDocument()
    expect(screen.getByText('Gmail is unavailable right now.')).toBeInTheDocument()
    expect(screen.getByText(/Reference material/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /propose action/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /search gmail/i })).not.toBeInTheDocument()
  })

  it('collapses routine results into chips that expand into the shared card', async () => {
    const user = userEvent.setup()
    render(<CompactToolResults toolOutputs={[routine]} />)

    const chip = screen.getByRole('button', { name: /brave web search/i })
    expect(chip).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Routine search payload')).not.toBeInTheDocument()

    await user.click(chip)
    expect(chip).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Routine search payload')).toBeInTheDocument()
  })
})
