import { useCallback, useEffect, useRef, useState } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { LocalCommandStatus, LocalToolScope } from '../types/telemetry'

const LOCAL_TOOL_SCOPES: readonly LocalToolScope[] = [
  'schedule',
  'weather',
  'f1',
  'mail',
  'search',
  'market',
  'briefings',
  'todo',
]

function isLocalToolScope(value: unknown): value is LocalToolScope {
  return typeof value === 'string' && LOCAL_TOOL_SCOPES.includes(value as LocalToolScope)
}

function parseLocalCommandStatus(value: unknown): LocalCommandStatus | null {
  if (!value || typeof value !== 'object') {
    return null
  }
  const record = value as Record<string, unknown>
  if (
    !isLocalToolScope(record.key) ||
    record.command !== `/${record.key}` ||
    typeof record.label !== 'string' ||
    typeof record.description !== 'string' ||
    typeof record.tool_count !== 'number' ||
    !Number.isFinite(record.tool_count) ||
    typeof record.estimated_schema_tokens !== 'number' ||
    !Number.isFinite(record.estimated_schema_tokens) ||
    typeof record.available !== 'boolean'
  ) {
    return null
  }
  return {
    key: record.key,
    command: record.command,
    label: record.label,
    description: record.description,
    tool_count: record.tool_count,
    estimated_schema_tokens: record.estimated_schema_tokens,
    available: record.available,
    unavailable_reason:
      typeof record.unavailable_reason === 'string'
        ? record.unavailable_reason
        : null,
  }
}

function parseLocalCommandStatuses(value: unknown): LocalCommandStatus[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map(parseLocalCommandStatus)
    .filter((command): command is LocalCommandStatus => command !== null)
}

export interface UseLocalCommandsResult {
  commands: LocalCommandStatus[]
  refreshCommands: () => Promise<void>
}

export function useLocalCommands(enabled: boolean): UseLocalCommandsResult {
  const [commands, setCommands] = useState<LocalCommandStatus[]>([])
  const requestSequence = useRef(0)

  const refreshCommands = useCallback(async (): Promise<void> => {
    const requestId = ++requestSequence.current
    try {
      const response = await fetch(API_ENDPOINTS.agentCommands)
      const parsed = response.ok
        ? parseLocalCommandStatuses(await response.json())
        : []
      if (requestSequence.current === requestId) {
        setCommands(parsed)
      }
    } catch {
      if (requestSequence.current === requestId) {
        setCommands([])
      }
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      return
    }
    const timeoutId = window.setTimeout(() => {
      void refreshCommands()
    }, 0)
    return () => {
      window.clearTimeout(timeoutId)
      requestSequence.current += 1
    }
  }, [enabled, refreshCommands])

  return { commands, refreshCommands }
}
