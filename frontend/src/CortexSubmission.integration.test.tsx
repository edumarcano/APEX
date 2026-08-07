import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AskApexBar } from './components/AskApexBar'
import { PreflightDialog } from './components/PreflightDialog'
import { useCortex } from './hooks/useCortex'
import { usePreflight } from './hooks/usePreflight'
import { useToolCatalog } from './hooks/useToolCatalog'
import { API_ENDPOINTS } from './lib/api'
import { isLocalAgentKey } from './lib/agents'
import type { AgentKey, ToolCatalog } from './types/telemetry'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

function catalogFor(agent: AgentKey): ToolCatalog {
  return {
    agent,
    groups: [],
    tools: [],
    profiles: [{
      id: 'no_tools',
      name: 'No APEX Tools',
      description: 'No live tools.',
      tool_names: [],
      built_in: true,
      dynamic: false,
    }],
    default_profile_id: 'no_tools',
    default_profile_name: 'No APEX Tools',
    default_selected_tool_names: [],
    provider_hosted_tools: [],
    context_window: agent === 'panthera' ? null : 4096,
    reserved_response_tokens: agent === 'panthera' ? null : 512,
  }
}

function preflightResponse(): Response {
  return new Response(JSON.stringify({
    warnings: [],
    blockers: [],
    can_proceed: true,
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function installFetchMock(deferPreflight = false): {
  catalogRequests: Array<{ agent: AgentKey; response: Deferred<Response> }>
  settingsRequests: Array<Deferred<Response>>
  preflightRequests: Array<Deferred<Response>>
  queryRequests: Array<Deferred<Response>>
  queryBodies: Record<string, unknown>[]
} {
  const catalogRequests: Array<{ agent: AgentKey; response: Deferred<Response> }> = []
  const settingsRequests: Array<Deferred<Response>> = []
  const preflightRequests: Array<Deferred<Response>> = []
  const queryRequests: Array<Deferred<Response>> = []
  const queryBodies: Record<string, unknown>[] = []

  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url = new URL(String(input))
      if (url.pathname.endsWith('/cortex/tool-catalog')) {
        const agent = url.searchParams.get('agent') as AgentKey
        const response = deferred<Response>()
        catalogRequests.push({ agent, response })
        return response.promise
      }
      if (url.pathname.endsWith('/settings') && init?.method === 'PATCH') {
        const response = deferred<Response>()
        settingsRequests.push(response)
        return response.promise
      }
      if (url.pathname.endsWith('/preflight')) {
        if (deferPreflight) {
          const response = deferred<Response>()
          preflightRequests.push(response)
          return response.promise
        }
        return Promise.resolve(preflightResponse())
      }
      if (url.pathname.endsWith('/cortex/query')) {
        queryBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
        const response = deferred<Response>()
        queryRequests.push(response)
        return response.promise
      }
      if (url.pathname.endsWith('/agents')) {
        return Promise.resolve(new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }))
      }
      return Promise.resolve(new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    }),
  )

  return { catalogRequests, settingsRequests, preflightRequests, queryRequests, queryBodies }
}

function queryResponse(): Response {
  return new Response(JSON.stringify({
    answer: 'Fresh Cortex answer.',
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function SubmissionHarness({
  initialAgent,
  alternateAgent,
}: {
  initialAgent: AgentKey
  alternateAgent: AgentKey
}): ReactElement {
  const [activeAgent, setActiveAgent] = useState(initialAgent)
  const [draftPrompt, setDraftPrompt] = useState('')
  const [sessionId, setSessionId] = useState('session-0')
  const [submissionPending, setSubmissionPending] = useState(false)
  const activeAgentRef = useRef(activeAgent)
  const submissionPendingRef = useRef(false)

  useEffect(() => {
    activeAgentRef.current = activeAgent
  }, [activeAgent])

  const cortex = useCortex(false, activeAgent)
  const catalogState = useToolCatalog(activeAgent)
  const preflight = usePreflight()
  const { clearCortexSession, queryAgent } = cortex
  const { requestOperation } = preflight

  const submit = useCallback(async (
    prompt: string,
    agent: AgentKey,
    selectedToolNames: string[],
    toolProfileId: string | null,
  ): Promise<boolean> => {
    if (submissionPendingRef.current) return false
    submissionPendingRef.current = true
    setSubmissionPending(true)
    try {
      const isCurrentSelection = (): boolean =>
        activeAgentRef.current === agent &&
        catalogState.selectionReady &&
        catalogState.catalog?.agent === agent
      if (!isCurrentSelection()) return false

      const resolution = await requestOperation('cortex_query', {
        synthesis_agent: agent,
        involves_cloud: !isLocalAgentKey(agent),
      })
      if (resolution !== 'proceed' || !isCurrentSelection()) return false

      void queryAgent(prompt, agent, {
        selectedToolNames,
        toolProfileId,
        sessionId,
      })
      return true
    } finally {
      submissionPendingRef.current = false
      setSubmissionPending(false)
    }
  }, [
    catalogState.catalog,
    catalogState.selectionReady,
    queryAgent,
    requestOperation,
    sessionId,
  ])

  const switchAgent = useCallback((): void => {
    const staleRefresh = catalogState.refreshCatalog
    setActiveAgent(alternateAgent)
    void fetch(API_ENDPOINTS.settings, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ask_apex: { runtime: 'local', local_agent: alternateAgent } }),
    }).then(() => {
      void staleRefresh()
    })
  }, [alternateAgent, catalogState.refreshCatalog])

  const startNewSession = useCallback((): void => {
    clearCortexSession(activeAgent)
    setSessionId('session-1')
  }, [activeAgent, clearCortexSession])

  return (
    <div>
      <button type="button" onClick={switchAgent}>Switch agent</button>
      <button type="button" onClick={startNewSession}>New session</button>
      <button type="button" onClick={() => setDraftPrompt('Queued after the switch')}>Queue draft</button>
      <output data-testid="active-agent">{activeAgent}</output>
      <output data-testid="catalog-agent">{catalogState.catalog?.agent ?? 'none'}</output>
      <output data-testid="selection-ready">{String(catalogState.selectionReady)}</output>
      <output data-testid="history">{JSON.stringify(cortex.cortexHistory)}</output>
      <output data-testid="session-id">{sessionId}</output>
      <AskApexBar
        presentation="cortex"
        activeAgent={activeAgent}
        onSubmit={submit}
        agentsStatus={[]}
        catalog={catalogState.catalog}
        selectedToolNames={catalogState.selectedToolNames}
        activeToolProfileId={catalogState.activeToolProfileId}
        selectionReady={catalogState.selectionReady}
        submissionPending={submissionPending}
        isSubmitting={cortex.isCortexQuerying}
        draftPrompt={draftPrompt}
        onDraftChange={setDraftPrompt}
      />
      <PreflightDialog
        open={preflight.dialogOpen}
        operation={preflight.pendingOperation}
        warnings={preflight.warnings}
        blockers={preflight.blockers}
        isChecking={preflight.isChecking}
        error={preflight.error}
        onChoice={preflight.resolveDialog}
      />
    </div>
  )
}

describe('Cortex submission lifecycle', () => {
  afterEach(() => {
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it.each([
    ['panthera', 'mus'],
    ['mus', 'panthera'],
  ] as const)(
    'hydrates %s after switching to it and starting a new session',
    async (initialAgent, alternateAgent) => {
      const api = installFetchMock()
      const user = userEvent.setup()
      render(
        <SubmissionHarness
          initialAgent={initialAgent}
          alternateAgent={alternateAgent}
        />,
      )

      await waitFor(() => expect(api.catalogRequests).toHaveLength(1))
      api.catalogRequests[0].response.resolve(new Response(JSON.stringify(catalogFor(initialAgent)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      await waitFor(() => expect(screen.getByTestId('selection-ready')).toHaveTextContent('true'))

      const input = screen.getByLabelText('Ask APEX query')
      await user.type(input, 'Initial request')
      await user.click(screen.getByRole('button', { name: 'Send query' }))
      await waitFor(() => expect(api.queryBodies).toHaveLength(1))
      await waitFor(() => expect(input).toHaveValue(''))
      api.queryRequests[0].resolve(queryResponse())
      await waitFor(() => expect(screen.getByRole('button', { name: 'New session' })).toBeEnabled())

      await user.click(screen.getByRole('button', { name: 'Switch agent' }))
      await user.click(screen.getByRole('button', { name: 'New session' }))
      await waitFor(() => expect(api.catalogRequests).toHaveLength(2))
      expect(screen.getByTestId('catalog-agent')).toHaveTextContent('none')
      expect(screen.getByTestId('selection-ready')).toHaveTextContent('false')

      await user.click(screen.getByRole('button', { name: 'Queue draft' }))
      expect(input).toHaveValue('Queued after the switch')
      expect(screen.getByRole('button', { name: 'Send query' })).toBeDisabled()

      await act(async () => {
        api.settingsRequests[0].resolve(new Response('{}', { status: 200 }))
        await Promise.resolve()
      })
      expect(api.catalogRequests).toHaveLength(2)

      api.catalogRequests[1].response.resolve(new Response(JSON.stringify(catalogFor(alternateAgent)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      await waitFor(() => {
        expect(screen.getByTestId('catalog-agent')).toHaveTextContent(alternateAgent)
        expect(screen.getByTestId('selection-ready')).toHaveTextContent('true')
      })
      expect(input).toHaveValue('Queued after the switch')

      await user.click(screen.getByRole('button', { name: 'Send query' }))
      await waitFor(() => expect(api.queryBodies).toHaveLength(2))
      expect(api.queryBodies[1]).toMatchObject({
        agent: alternateAgent,
        history: [],
        session_id: 'session-1',
      })
      await waitFor(() => expect(input).toHaveValue(''))
      api.queryRequests[1].resolve(queryResponse())
      await waitFor(() => expect(screen.getByTestId('history')).toHaveTextContent('Queued after the switch'))
      expect(screen.getByTestId('catalog-agent')).toHaveTextContent(alternateAgent)
      expect(screen.getByTestId('history')).not.toHaveTextContent('Initial request')
    },
  )

  it('retains the draft when operational preflight is cancelled and blocks duplicate sends', async () => {
    const api = installFetchMock(true)
    const user = userEvent.setup()
    render(<SubmissionHarness initialAgent="panthera" alternateAgent="mus" />)

    await waitFor(() => expect(api.catalogRequests).toHaveLength(1))
    api.catalogRequests[0].response.resolve(new Response(JSON.stringify(catalogFor('panthera')), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    await waitFor(() => expect(screen.getByTestId('selection-ready')).toHaveTextContent('true'))

    const input = screen.getByLabelText('Ask APEX query')
    await user.type(input, 'Keep across cancellation')
    await user.click(screen.getByRole('button', { name: 'Send query' }))
    await waitFor(() => expect(api.preflightRequests).toHaveLength(1))
    expect(screen.getByRole('button', { name: 'Preparing query' })).toBeDisabled()
    expect(input).toHaveValue('Keep across cancellation')
    expect(api.queryBodies).toHaveLength(0)

    api.preflightRequests[0].resolve(new Response(JSON.stringify({
      warnings: [],
      blockers: [{ code: 'runtime_unavailable', message: 'Runtime unavailable.' }],
      can_proceed: false,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Activation Blocked' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Close preflight dialog' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Send query' })).toBeEnabled())
    expect(input).toHaveValue('Keep across cancellation')
    expect(api.queryBodies).toHaveLength(0)
  })
})
