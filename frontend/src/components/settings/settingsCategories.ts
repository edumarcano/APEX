import {
  Activity,
  Blocks,
  Database,
  Sparkles,
  Volume2,
  MonitorCog,
  type LucideIcon,
} from 'lucide-react'

import { diffSettingsPatch } from '../../lib/settings'
import type { RuntimeSettings } from '../../types/settings'

export type SettingsCategoryKey =
  | 'data_sources'
  | 'intelligence'
  | 'integrations'
  | 'voice_audio'
  | 'desktop'
  | 'system_status'

export interface SettingsCategoryConfig {
  key: SettingsCategoryKey
  label: string
  icon: LucideIcon
  description: string
}

export const SETTINGS_CATEGORIES: readonly SettingsCategoryConfig[] = [
  {
    key: 'data_sources',
    label: 'Data Sources',
    icon: Database,
    description: 'Feeds, markets, sports, calendar',
  },
  {
    key: 'intelligence',
    label: 'Intelligence',
    icon: Sparkles,
    description: 'Persona, queries, llama.cpp',
  },
  {
    key: 'integrations',
    label: 'Integrations',
    icon: Blocks,
    description: 'MCP tools, Microsoft To Do, reports',
  },
  {
    key: 'voice_audio',
    label: 'Voice & Audio',
    icon: Volume2,
    description: 'Speech synthesis, engine, audio',
  },
  {
    key: 'desktop',
    label: 'Desktop',
    icon: MonitorCog,
    description: 'Startup, tray, notifications',
  },
  {
    key: 'system_status',
    label: 'System Status',
    icon: Activity,
    description: 'Connectors, AI models, flags',
  },
]

export function getCategoryDirtyMap(
  baseline: RuntimeSettings | null,
  draft: RuntimeSettings | null,
): Record<SettingsCategoryKey, boolean> {
  if (!baseline || !draft) {
    return {
      data_sources: false,
      intelligence: false,
      integrations: false,
      voice_audio: false,
      desktop: false,
      system_status: false,
    }
  }

  const patch = diffSettingsPatch(baseline, draft)

  return {
    data_sources: Boolean(
      patch.features ||
      patch.modules ||
      patch.football ||
      patch.market ||
      patch.calendar,
    ),
    intelligence: Boolean(
      patch.user_designation !== undefined ||
      patch.agent_display_name !== undefined ||
      patch.ask_apex ||
      patch.llama_cpp,
    ),
    integrations: Boolean(
      patch.mcp ||
      patch.microsoft_todo ||
      patch.activity_report_folder,
    ),
    voice_audio: Boolean(patch.voice),
    desktop: Boolean(patch.desktop),
    system_status: false,
  }
}

export function resolveConnectorStatus(
  connectorKey: string,
  enabled: boolean,
  failedConnectors: string[],
  hasTelemetryEvidence: boolean,
): { value: string; tone: 'neutral' | 'ok' | 'warn' | 'error' } {
  if (!enabled) {
    return { value: 'Disabled', tone: 'neutral' }
  }
  if (connectorKey === 'market') {
    return { value: 'Enabled', tone: 'ok' }
  }
  if (!hasTelemetryEvidence) {
    return { value: 'Not yet checked', tone: 'neutral' }
  }

  const failedSet = new Set(failedConnectors.map((id) => id.trim().toLowerCase()))
  const connectorNames =
    connectorKey === 'sports'
      ? ['f1', 'football']
      : [connectorKey]

  if (connectorNames.some((name) => failedSet.has(name))) {
    return { value: 'Failed last refresh', tone: 'error' }
  }
  return { value: 'Clear last refresh', tone: 'ok' }
}

export function describeLlamaCppServerStatus(runtime: {
  status: { state: string } | null
  loading: boolean
  unavailable: boolean
}): string {
  if (runtime.unavailable) {
    return 'Status unavailable'
  }
  if (!runtime.status) {
    return runtime.loading ? 'Checking…' : 'Unknown'
  }
  switch (runtime.status.state) {
    case 'disabled':
      return 'Disabled'
    case 'external_connected':
      return 'External server connected'
    case 'managed_running':
      return 'Managed server running'
    case 'starting':
      return 'Starting managed server'
    case 'managed_stopped':
      return 'Managed server stopped'
    case 'startup_failed':
      return 'Startup failed'
    default:
      return 'Unknown'
  }
}
