import type { ReactElement } from 'react'
import { Activity, Server, Sliders } from 'lucide-react'

import { SettingsCard, StatusRow, type SettingsStatusTone } from '../SettingsControls'
import { resolveConnectorStatus } from './settingsCategories'
import type { RuntimeSettings, SettingsResponse } from '../../types/settings'

const FEATURE_CONTROLS: readonly {
  key: keyof RuntimeSettings['features']
  label: string
}[] = [
  { key: 'weather', label: 'Weather' },
  { key: 'sports', label: 'Sports' },
  { key: 'email', label: 'Email' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'market', label: 'Market' },
]

interface SystemStatusViewProps {
  titleId: string
  envelope: SettingsResponse | null
  baseline: RuntimeSettings | null
  providerRows: {
    cloud: { value: string; tone: SettingsStatusTone }
    local: { value: string; tone: SettingsStatusTone }
    activeModel: string
  }
  failedConnectors: string[]
  hasTelemetryEvidence: boolean
}

export default function SystemStatusView({
  titleId,
  envelope,
  baseline,
  providerRows,
  failedConnectors,
  hasTelemetryEvidence,
}: SystemStatusViewProps): ReactElement {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Runtime Status / Connector Health Card */}
      <SettingsCard
        id={`${titleId}-runtime`}
        title="Runtime Status"
        icon={Activity}
        badgeText="Connectors"
      >
        <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
          <StatusRow label="Backend" value="Reachable" tone="ok" />
          {FEATURE_CONTROLS.map((control) => {
            const connectorStatus = resolveConnectorStatus(
              control.key,
              baseline?.features[control.key] ?? false,
              failedConnectors,
              hasTelemetryEvidence,
            )
            return (
              <StatusRow
                key={`status-${control.key}`}
                label={control.label}
                value={connectorStatus.value}
                tone={connectorStatus.tone}
              />
            )
          })}
        </div>
      </SettingsCard>

      {/* AI Provider Infrastructure Card */}
      <SettingsCard
        id={`${titleId}-ai-providers`}
        title="AI Providers"
        icon={Server}
        badgeText="Cloud & Local"
      >
        <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
          <StatusRow
            label="Cloud models"
            value={providerRows.cloud.value}
            tone={providerRows.cloud.tone}
          />
          <StatusRow
            label="Local models"
            value={providerRows.local.value}
            tone={providerRows.local.tone}
          />
          <StatusRow
            label="Active local model"
            value={providerRows.activeModel}
          />
        </div>
      </SettingsCard>

      {/* Environment Flags Card */}
      <SettingsCard
        id={`${titleId}-env-flags`}
        title="Environment Flags"
        icon={Sliders}
        badgeText="Runtime Overrides"
        className="lg:col-span-2"
      >
        <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
          <StatusRow
            label="DEV_MODE"
            value={envelope?.dev_mode_active ? 'Active (read-only)' : 'Off'}
            tone={envelope?.dev_mode_active ? 'warn' : 'neutral'}
          />
          <StatusRow
            label="DEMO_MODE"
            value={envelope?.demo_mode_active ? 'Active (read-only)' : 'Off'}
            tone={envelope?.demo_mode_active ? 'warn' : 'neutral'}
          />
          <StatusRow
            label="Local override"
            value={
              envelope?.local_override_active
                ? 'Active (config.local.json)'
                : envelope?.local_file_present
                  ? 'File present, inactive'
                  : 'None'
            }
            tone={envelope?.local_override_active ? 'ok' : 'neutral'}
          />
          {envelope?.load_warning ? (
            <StatusRow
              label="Load warning"
              value={envelope.load_warning}
              tone="warn"
            />
          ) : null}
        </div>
      </SettingsCard>
    </div>
  )
}
