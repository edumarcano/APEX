import { render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { describe, expect, it } from 'vitest'

import { DEFAULT_SYSTEM_DIAGNOSTICS } from '../types/telemetry'
import { SystemDiagnostics } from './SystemDiagnostics'

function renderDiagnostics(overrides: Partial<ComponentProps<typeof SystemDiagnostics>> = {}) {
  return render(
    <SystemDiagnostics
      diagnostics={DEFAULT_SYSTEM_DIAGNOSTICS}
      diagnosticsStatus="ready"
      status="idle"
      confidenceScore={0}
      {...overrides}
    />,
  )
}

describe('SystemDiagnostics', () => {
  it('keeps workspace controls visually grouped with, but semantically outside, the sync-health trigger', () => {
    renderDiagnostics({
      workspaceNavigation: <nav aria-label="Workspace"><button type="button">Overview</button><button type="button">Cortex</button></nav>,
    })

    const workspace = screen.getByRole('navigation', { name: 'Workspace' })
    expect(workspace).toBeInTheDocument()
    expect(workspace.closest('[role="button"]')).toBeNull()
    expect(screen.getByRole('button', { name: 'APEX sync health' })).toBeInTheDocument()
  })
})
