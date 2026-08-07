import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type {
  AgentKey,
  ToolCatalog,
  ToolCatalogGroup,
  ToolCatalogTool,
  ToolProfileMetadata,
} from '../types/telemetry'

const SESSION_PREFIX = 'apex.tool-selection.'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
function parseTool(value: unknown): ToolCatalogTool | null {
  if (!isRecord(value)) return null
  if (
    typeof value.name !== 'string' ||
    typeof value.label !== 'string' ||
    typeof value.description !== 'string' ||
    (value.origin !== 'native' && value.origin !== 'mcp') ||
    typeof value.source_id !== 'string' ||
    (value.apex_family !== null && typeof value.apex_family !== 'string') ||
    !['read', 'write', 'destructive'].includes(String(value.risk)) ||
    typeof value.available !== 'boolean' ||
    typeof value.allowed_for_agent !== 'boolean' ||
    typeof value.estimated_schema_tokens !== 'number'
  ) {
    return null
  }
  return {
    name: value.name,
    label: value.label,
    description: value.description,
    origin: value.origin,
    source_id: value.source_id,
    apex_family: value.apex_family as string | null,
    risk: value.risk as ToolCatalogTool['risk'],
    available: value.available,
    unavailable_reason:
      typeof value.unavailable_reason === 'string' ? value.unavailable_reason : null,
    estimated_schema_tokens: value.estimated_schema_tokens,
    allowed_for_agent: value.allowed_for_agent,
  }
}
function parseGroup(value: unknown): ToolCatalogGroup | null {
  if (!isRecord(value) || !Array.isArray(value.tools)) return null
  if (
    typeof value.id !== 'string' ||
    typeof value.label !== 'string' ||
    (value.kind !== 'apex_family' && value.kind !== 'mcp_server') ||
    typeof value.tool_count !== 'number' ||
    typeof value.schema_token_subtotal !== 'number'
  ) {
    return null
  }
  const tools = value.tools
    .map(parseTool)
    .filter((tool): tool is ToolCatalogTool => tool !== null)
  return {
    id: value.id,
    label: value.label,
    kind: value.kind,
    tool_count: value.tool_count,
    schema_token_subtotal: value.schema_token_subtotal,
    tools,
  }
}

function parseProfile(value: unknown): ToolProfileMetadata | null {
  if (
    !isRecord(value) ||
    typeof value.id !== 'string' ||
    typeof value.name !== 'string' ||
    typeof value.description !== 'string' ||
    !Array.isArray(value.tool_names) ||
    !value.tool_names.every((name) => typeof name === 'string') ||
    typeof value.built_in !== 'boolean' ||
    typeof value.dynamic !== 'boolean'
  ) {
    return null
  }
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    tool_names: value.tool_names,
    built_in: value.built_in,
    dynamic: value.dynamic,
  }
}

function parseCatalog(value: unknown, agent: AgentKey): ToolCatalog | null {
  if (!isRecord(value) || !Array.isArray(value.groups) || !Array.isArray(value.tools)) {
    return null
  }
  const groups = value.groups
    .map(parseGroup)
    .filter((group): group is ToolCatalogGroup => group !== null)
  const tools = value.tools
    .map(parseTool)
    .filter((tool): tool is ToolCatalogTool => tool !== null)
  const profiles = Array.isArray(value.profiles)
    ? value.profiles
      .map(parseProfile)
      .filter((profile): profile is ToolProfileMetadata => profile !== null)
    : []
  if (
    value.agent !== agent ||
    typeof value.default_profile_id !== 'string' ||
    typeof value.default_profile_name !== 'string' ||
    !Array.isArray(value.default_selected_tool_names) ||
    !value.default_selected_tool_names.every((name) => typeof name === 'string')
  ) {
    return null
  }
  return {
    agent,
    groups,
    tools,
    profiles,
    default_profile_id: value.default_profile_id,
    default_profile_name: value.default_profile_name,
    default_selected_tool_names: value.default_selected_tool_names,
    provider_hosted_tools: Array.isArray(value.provider_hosted_tools)
      ? value.provider_hosted_tools.filter(
        (name): name is string => typeof name === 'string',
      )
      : [],
    context_window:
      typeof value.context_window === 'number' ? value.context_window : null,
    reserved_response_tokens:
      typeof value.reserved_response_tokens === 'number'
        ? value.reserved_response_tokens
        : null,
  }
}

interface SessionSelection {
  names: string[]
  profileId: string | null
}

interface PendingSelection {
  agent: AgentKey
  selection: SessionSelection | null
}

function readSessionSelection(agent: AgentKey): SessionSelection | null {
  try {
    const raw = globalThis.sessionStorage?.getItem(`${SESSION_PREFIX}${agent}`)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (
      !isRecord(parsed) ||
      !Array.isArray(parsed.names) ||
      !parsed.names.every((name) => typeof name === 'string') ||
      (parsed.profileId !== null && typeof parsed.profileId !== 'string')
    ) {
      return null
    }
    return { names: parsed.names, profileId: parsed.profileId as string | null }
  } catch {
    return null
  }
}

function writeSessionSelection(agent: AgentKey, selection: SessionSelection): void {
  try {
    globalThis.sessionStorage?.setItem(
      `${SESSION_PREFIX}${agent}`,
      JSON.stringify(selection),
    )
  } catch {
    // Session persistence is advisory and must not block querying.
  }
}

function normalizeNames(names: string[]): string[] {
  return [...new Set(names.map((name) => name.trim()).filter(Boolean))]
}

function availableToolNames(catalog: ToolCatalog): string[] {
  return catalog.tools
    .filter((tool) => tool.available && tool.allowed_for_agent)
    .map((tool) => tool.name)
}

function sameNames(left: string[], right: string[]): boolean {
  const normalizedLeft = new Set(normalizeNames(left))
  const normalizedRight = new Set(normalizeNames(right))
  return (
    normalizedLeft.size === normalizedRight.size &&
    [...normalizedLeft].every((name) => normalizedRight.has(name))
  )
}

function resolvedProfileNames(
  catalog: ToolCatalog,
  profile: ToolProfileMetadata,
): string[] {
  return profile.dynamic ? availableToolNames(catalog) : normalizeNames(profile.tool_names)
}

export interface UseToolCatalogResult {
  catalog: ToolCatalog | null
  isLoading: boolean
  error: string | null
  selectedToolNames: string[]
  activeToolProfileId: string | null
  selectionReady: boolean
  setSelectedToolNames: (names: string[]) => void
  setToolSelection: (names: string[], profileId: string | null) => void
  applyToolProfile: (profileId: string) => void
  refreshCatalog: () => Promise<void>
}

export function useToolCatalog(activeAgent: AgentKey): UseToolCatalogResult {
  const [catalog, setCatalog] = useState<ToolCatalog | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedToolNames, setSelectedToolNamesState] = useState<string[]>([])
  const [activeToolProfileId, setActiveToolProfileId] = useState<string | null>(null)
  const [selectionReady, setSelectionReady] = useState(false)
  const pendingSelection = useRef<PendingSelection | null>(null)
  const hydratedAgent = useRef<AgentKey | null>(null)
  const activeAgentRef = useRef(activeAgent)
  const requestGenerations = useRef(new Map<AgentKey, number>())

  useEffect(() => {
    activeAgentRef.current = activeAgent
  }, [activeAgent])

  const setSelection = useCallback(
    (names: string[], profileId: string | null = null): void => {
      const normalized = [
        ...normalizeNames(names),
      ]
      setSelectedToolNamesState(normalized)
      setActiveToolProfileId(profileId)
      writeSessionSelection(activeAgent, { names: normalized, profileId })
    },
    [activeAgent],
  )

  const refreshCatalog = useCallback(async (): Promise<void> => {
    const requestedAgent = activeAgent
    if (activeAgentRef.current !== requestedAgent) return
    const requestId = (requestGenerations.current.get(requestedAgent) ?? 0) + 1
    requestGenerations.current.set(requestedAgent, requestId)
    const isCurrentRequest = (): boolean =>
      activeAgentRef.current === requestedAgent &&
      requestGenerations.current.get(requestedAgent) === requestId
    setIsLoading(true)
    setError(null)
    try {
      const response = await fetch(API_ENDPOINTS.cortexToolCatalog(requestedAgent))
      if (!response.ok) {
        throw new Error(`Tool catalog unavailable (${response.status})`)
      }
      const parsed = parseCatalog(await response.json(), requestedAgent)
      if (!parsed) throw new Error('APEX returned an invalid tool catalog.')
      if (isCurrentRequest()) {
        setCatalog(parsed)
      }
    } catch (fetchError) {
      if (isCurrentRequest()) {
        setError(fetchError instanceof Error ? fetchError.message : 'Tool catalog unavailable.')
        setCatalog(null)
      }
    } finally {
      if (isCurrentRequest()) setIsLoading(false)
    }
  }, [activeAgent])

  useEffect(() => {
    const stored = readSessionSelection(activeAgent)
    pendingSelection.current = { agent: activeAgent, selection: stored }
    hydratedAgent.current = null
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Agent changes reset the visible selection while the new catalog hydrates.
    setCatalog(null)
    setSelectionReady(false)
    setSelectedToolNamesState(stored?.names ?? [])
    setActiveToolProfileId(stored?.profileId ?? null)
    void refreshCatalog()
  }, [activeAgent, refreshCatalog])

  useEffect(() => {
    if (!catalog || catalog.agent !== activeAgent || hydratedAgent.current === activeAgent) {
      return
    }
    hydratedAgent.current = activeAgent
    const pending = pendingSelection.current
    const stored = pending?.agent === activeAgent ? pending.selection : null
    const storedProfile = stored?.profileId
      ? catalog.profiles.find((item) => item.id === stored.profileId)
      : null
    const defaultProfile = catalog.profiles.find(
      (item) => item.id === catalog.default_profile_id,
    )
    const names = stored
      ? storedProfile?.dynamic
        ? resolvedProfileNames(catalog, storedProfile)
        : stored.names
      : defaultProfile?.dynamic
        ? resolvedProfileNames(catalog, defaultProfile)
        : catalog.default_selected_tool_names
    let profileId: string | null = stored?.profileId ?? catalog.default_profile_id
    if (stored?.profileId && !storedProfile) {
      profileId = null
    } else if (stored?.profileId && storedProfile?.dynamic) {
      profileId = storedProfile.id
    } else if (stored?.profileId && storedProfile) {
      const expectedNames = resolvedProfileNames(catalog, storedProfile)
      if (!sameNames(expectedNames, names)) {
        profileId = null
      }
    }
    const normalizedNames = normalizeNames(names)
    setSelectedToolNamesState(normalizedNames)
    setActiveToolProfileId(profileId)
    writeSessionSelection(activeAgent, { names: normalizedNames, profileId })
    setSelectionReady(true)
  }, [activeAgent, catalog])

  useEffect(() => {
    if (!catalog || catalog.agent !== activeAgent || hydratedAgent.current !== activeAgent) {
      return
    }
    const activeProfile = activeToolProfileId
      ? catalog.profiles.find((item) => item.id === activeToolProfileId)
      : null
    if (activeProfile?.dynamic) {
      const refreshedNames = resolvedProfileNames(catalog, activeProfile)
      if (!sameNames(refreshedNames, selectedToolNames)) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- Dynamic profiles synchronize their resolved names with the refreshed catalog.
        setSelection(refreshedNames, activeToolProfileId)
      }
      return
    }
    if (activeToolProfileId) {
      const expectedNames = activeProfile
        ? resolvedProfileNames(catalog, activeProfile)
        : null
      if (!expectedNames || !sameNames(expectedNames, selectedToolNames)) {
        setActiveToolProfileId(null)
        writeSessionSelection(activeAgent, { names: selectedToolNames, profileId: null })
      }
    }
  }, [activeAgent, activeToolProfileId, catalog, selectedToolNames, setSelection])

  const applyToolProfile = useCallback(
    (profileId: string): void => {
      if (!catalog) return
      const profile = catalog.profiles.find((item) => item.id === profileId)
      if (!profile) return
      const names = profile.dynamic
        ? catalog.tools
          .filter((tool) => tool.available && tool.allowed_for_agent)
          .map((tool) => tool.name)
        : profile.tool_names
      setSelection(names, profile.id)
    },
    [catalog, setSelection],
  )

  const effectiveCatalog = catalog?.agent === activeAgent ? catalog : null
  const effectiveSelectionReady =
    selectionReady && effectiveCatalog !== null

  return {
    catalog: effectiveCatalog,
    selectionReady: effectiveSelectionReady,
    isLoading,
    error,
    selectedToolNames,
    activeToolProfileId,
    setSelectedToolNames: (names) => setSelection(names),
    setToolSelection: setSelection,
    applyToolProfile,
    refreshCatalog,
  }
}
