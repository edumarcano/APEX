import { fireEvent, render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { DEFAULT_SYSTEM_DIAGNOSTICS } from '../types/telemetry'
import { SystemDiagnostics } from './SystemDiagnostics'

function renderDiagnostics(overrides: Partial<ComponentProps<typeof SystemDiagnostics>> = {}) {
  return render(
    <SystemDiagnostics
      diagnostics={DEFAULT_SYSTEM_DIAGNOSTICS}
      diagnosticsStatus="ready"
      {...overrides}
    />,
  )
}

describe('SystemDiagnostics', () => {
  it('keeps workspace controls grouped with the stable APEX identity pill', () => {
    renderDiagnostics({
      workspaceNavigation: <nav aria-label="Workspace"><button type="button">Overview</button><button type="button">Cortex</button></nav>,
    })

    const workspace = screen.getByRole('navigation', { name: 'Workspace' })
    expect(workspace).toBeInTheDocument()
    expect(workspace.closest('[role="button"]')).toBeNull()
    expect(screen.queryByRole('button', { name: /APEX sync health/i })).not.toBeInTheDocument()
  })

  it('shows aggregate connector readiness and an accessible health inspector', () => {
    const onRefreshConnectors = vi.fn()
    renderDiagnostics({
      connectorHealth: [
        { name: 'email', status: 'healthy', freshness: 'live', reason_code: 'ok', observed_at: new Date().toISOString() },
        { name: 'calendar', status: 'unavailable', freshness: 'none', reason_code: 'unauthorized', observed_at: new Date().toISOString() },
        { name: 'news', status: 'disabled', freshness: 'none', reason_code: 'disabled', observed_at: null },
      ],
      onRefreshConnectors,
    })

    const trigger = screen.getByRole('button', { name: /Connectors · 1 ready · 1 issue/i })
    fireEvent.click(trigger)

    expect(screen.getByRole('dialog', { name: 'Connector health' })).toBeVisible()
    expect(screen.getByText('Email')).toBeVisible()
    expect(screen.getByText('Ready')).toBeVisible()
    expect(screen.getByText('Unauthorized')).toBeVisible()
    expect(screen.getByText('Not configured')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh checks' }))
    expect(onRefreshConnectors).toHaveBeenCalledOnce()
  })
})
