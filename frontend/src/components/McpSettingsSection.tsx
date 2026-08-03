import type { ReactElement } from 'react'

import type { McpStatusState } from '../hooks/useMcpStatus'
import { MCP_PROVIDERS, type McpProviderId } from '../lib/mcpProviders'
import type { McpSettings, SettingsEffectiveTiming } from '../types/settings'
import {
  SectionHeading,
  SettingsToggle,
  StatusRow,
  type SettingsStatusTone,
} from './SettingsControls'

interface McpSettingsSectionProps {
  sectionId: string
  baseline: McpSettings | null
  draft: McpSettings
  timing: SettingsEffectiveTiming
  runtime: McpStatusState
  onChange: (updater: (current: McpSettings) => McpSettings) => void
}

interface McpProviderPresentation {
  value: string
  tone: SettingsStatusTone
  tools: string[]
}

function resolveProviderStatus(
  provider: McpProviderId,
  baseline: McpSettings | null,
  runtime: McpStatusState,
): McpProviderPresentation {
  if (!baseline?.enabled || !baseline.servers[provider].enabled) {
    return { value: 'Disabled', tone: 'neutral', tools: [] }
  }
  if (runtime.unavailable) {
    return { value: 'Status unavailable', tone: 'warn', tools: [] }
  }
  const server = runtime.status?.servers.find((item) => item.id === provider)
  if (!server || server.status === 'configured') {
    return { value: 'Connecting', tone: 'neutral', tools: [] }
  }
  if (server.status === 'connected') {
    return { value: 'Connected', tone: 'ok', tools: server.registered_tools }
  }
  if (server.status === 'authentication-required') {
    return { value: 'Authentication required', tone: 'warn', tools: [] }
  }
  if (server.status === 'degraded') {
    return { value: 'Degraded', tone: 'error', tools: [] }
  }
  return { value: 'Disabled', tone: 'neutral', tools: [] }
}

export default function McpSettingsSection({
  sectionId,
  baseline,
  draft,
  timing,
  runtime,
  onChange,
}: McpSettingsSectionProps): ReactElement {
  return (
    <section className="space-y-2.5" aria-labelledby={sectionId}>
      <SectionHeading id={sectionId} title="External MCP Tools" />
      <p className="text-[11px] leading-relaxed text-zinc-500">
        Approved external tools become available to the selected Agent after Save.
        Credentials remain outside APEX settings.
      </p>
      <div className="space-y-2">
        <SettingsToggle
          id="settings-mcp-enabled"
          label="External MCP tools"
          checked={draft.enabled}
          timing={timing}
          onChange={(enabled) =>
            onChange((current) => ({ ...current, enabled }))
          }
        />
        <div className="ml-3 space-y-2 border-l border-white/10 pl-3">
          {MCP_PROVIDERS.map((provider) => {
            const providerRuntime = resolveProviderStatus(
              provider.id,
              baseline,
              runtime,
            )
            return (
              <div
                key={provider.id}
                className="space-y-1.5 rounded-lg border border-white/5 bg-white/[0.015] p-2"
              >
                <SettingsToggle
                  id={`settings-mcp-${provider.id}`}
                  label={provider.label}
                  checked={draft.servers[provider.id].enabled}
                  disabled={!draft.enabled}
                  timing={timing}
                  onChange={(enabled) =>
                    onChange((current) => ({
                      ...current,
                      servers: {
                        ...current.servers,
                        [provider.id]: { enabled },
                      },
                    }))
                  }
                />
                <p className="px-1 text-[10px] leading-relaxed text-zinc-500">
                  {provider.prerequisite}
                </p>
                <div className="px-1">
                  <StatusRow
                    label="Active runtime"
                    value={providerRuntime.value}
                    tone={providerRuntime.tone}
                  />
                  {providerRuntime.tools.length > 0 ? (
                    <p className="break-words py-1 font-mono text-[9px] leading-relaxed text-zinc-500">
                      {providerRuntime.tools.join(' · ')}
                    </p>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
