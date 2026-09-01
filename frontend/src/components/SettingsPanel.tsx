import {
  useCallback,
  useId,
  useMemo,
  useRef,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type RefObject,
} from 'react'
import { createPortal } from 'react-dom'
import { Settings, X } from 'lucide-react'

import McpSettingsSection from './McpSettingsSection'
import MicrosoftTodoSettingsSection from './MicrosoftTodoSettingsSection'
import { FootballTeamsEditor, MarketSymbolsEditor } from './SettingsListEditors'
import {
  SectionHeading,
  SettingsSelect,
  SettingsToggle,
  StatusRow,
} from './SettingsControls'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useLlamaCppStatus } from '../hooks/useLlamaCppStatus'
import { useMcpStatus, type McpStatusState } from '../hooks/useMcpStatus'
import { useMicrosoftTodoStatus } from '../hooks/useMicrosoftTodoStatus'
import { useSettingsEditor } from '../hooks/useSettingsEditor'
import {
  buildSettingsTimingRuntime,
  resolveEffectiveTiming,
} from '../lib/settings'
import type {
  AgentStatus,
  SystemState,
  TtsEngine,
} from '../types/telemetry'
import type {
  RuntimeSettings,
  SettingsResponse,
  VoiceGender,
  VoiceMode,
} from '../types/settings'

const FEATURE_CONTROLS: readonly {
  key: keyof RuntimeSettings['features']
  label: string
}[] = [
  { key: 'weather', label: 'Weather' },
  { key: 'sports', label: 'Sports' },
  { key: 'news', label: 'News' },
  { key: 'email', label: 'Email' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'market', label: 'Market' },
]

const MODULE_CONTROLS: readonly {
  key: keyof RuntimeSettings['modules']
  label: string
}[] = [
  { key: 'f1', label: 'Formula 1' },
  { key: 'football', label: 'Football' },
]


const ENGINE_OPTIONS: readonly { value: TtsEngine; label: string }[] = [
  { value: 'google', label: 'Google' },
  { value: 'pyttsx3', label: 'pyttsx3' },
  { value: 'kokoro', label: 'Kokoro' },
]

const GENDER_OPTIONS: readonly { value: VoiceGender; label: string }[] = [
  { value: 'female', label: 'Female' },
  { value: 'male', label: 'Male' },
]

const VOICE_MODE_OPTIONS: readonly { value: VoiceMode; label: string }[] = [
  { value: 'automatic', label: 'Automatic' },
  { value: 'manual', label: 'Manual' },
  { value: 'off', label: 'Off' },
]

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
  restoreFocusRef?: RefObject<HTMLElement | null>
  status: SystemState
  pipelineStep: number | null
  isSpeaking: boolean
  isCortexQuerying: boolean
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  failedConnectors: string[]
  hasBriefingEvidence: boolean
  onApplied: (response: SettingsResponse) => void
  mcpRuntime?: McpStatusState
}


function resolveConnectorStatus(
  connectorKey: string,
  enabled: boolean,
  failedConnectors: string[],
  hasBriefingEvidence: boolean,
): { value: string; tone: 'neutral' | 'ok' | 'warn' | 'error' } {
  if (!enabled) {
    return { value: 'Disabled', tone: 'neutral' }
  }
  if (connectorKey === 'market') {
    return { value: 'Enabled', tone: 'ok' }
  }
  if (!hasBriefingEvidence) {
    return { value: 'Not yet checked', tone: 'neutral' }
  }

  const failedSet = new Set(failedConnectors.map((id) => id.trim().toLowerCase()))
  const aliases =
    connectorKey === 'sports'
      ? ['sports', 'sports_f1', 'sports_football']
      : [connectorKey]

  if (aliases.some((alias) => failedSet.has(alias))) {
    return { value: 'Failed last briefing', tone: 'error' }
  }
  return { value: 'Clear last briefing', tone: 'ok' }
}

function describeLlamaCppServerStatus(runtime: {
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

export default function SettingsPanel({
  open,
  onClose,
  restoreFocusRef,
  status,
  pipelineStep,
  isSpeaking,
  isCortexQuerying,
  agentsStatus,
  agentsStatusHydrated,
  failedConnectors,
  hasBriefingEvidence,
  onApplied,
  mcpRuntime: sharedMcpRuntime,
}: SettingsPanelProps): ReactElement | null {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const {
    loadStatus,
    loadError,
    envelope,
    baseline,
    draft,
    isDirty,
    saving,
    saveError,
    setDraft,
    save,
  } = useSettingsEditor({ open, onApplied })
  const polledMcpRuntime = useMcpStatus(open && sharedMcpRuntime === undefined)
  const mcpRuntime = sharedMcpRuntime ?? polledMcpRuntime
  const llamaCppRuntime = useLlamaCppStatus(open)

  const microsoftTodoRuntime = useMicrosoftTodoStatus(open)
  useFocusTrap(open, dialogRef, restoreFocusRef)

  const timingRuntime = useMemo(
    () =>
      buildSettingsTimingRuntime({
        status,
        pipelineStep,
        isSpeaking,
        isCortexQuerying,
      }),
    [status, pipelineStep, isSpeaking, isCortexQuerying],
  )

  const featuresTiming = resolveEffectiveTiming('features', timingRuntime)
  const marketTiming = resolveEffectiveTiming('market', timingRuntime)
  const modulesTiming = resolveEffectiveTiming('modules', timingRuntime)
  const agentQueriesTiming = resolveEffectiveTiming('agent_queries', timingRuntime)
  const voiceTiming = resolveEffectiveTiming('voice', timingRuntime)
  const mcpTiming = resolveEffectiveTiming('mcp', timingRuntime)
  const llamaCppTiming = resolveEffectiveTiming('llama_cpp', timingRuntime)

  const requestClose = useCallback(() => {
    if (isDirty || saving) {
      const confirmed = window.confirm(
        'You have unsaved settings changes. Discard them and close?',
      )
      if (!confirmed) {
        return
      }
    }
    onClose()
  }, [isDirty, saving, onClose])

  const handleBackdropClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      if (event.target === event.currentTarget) {
        requestClose()
      }
    },
    [requestClose],
  )

  const handleDialogKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        requestClose()
      }
    },
    [requestClose],
  )

  const handleSave = useCallback(() => {
    void save().then((saved) => {
      if (saved) void mcpRuntime.refresh()
    })
  }, [save, mcpRuntime])

  const providerRows = useMemo(() => {
    const models = agentsStatus.flatMap((agent) => agent.model_catalog)
    const cloud = models.filter((model) => model.runtime === 'cloud')
    const local = models.filter((model) => model.runtime === 'local')
    const configuredCloud = cloud.filter((model) => model.status !== 'disabled').length
    const verifiedCloud = cloud.filter((model) => model.status === 'verified').length
    const localAvailable = local.some((model) => model.status === 'available')
    const activeLocal = local.find((model) => model.active && model.loaded_model)

    return {
      cloud: !agentsStatusHydrated
        ? { value: 'Checking…', tone: 'neutral' as const }
        : configuredCloud > 0
          ? { value: `${configuredCloud} configured · ${verifiedCloud} verified`, tone: verifiedCloud > 0 ? 'ok' as const : 'neutral' as const }
          : { value: 'Not configured', tone: 'error' as const },
      local: !agentsStatusHydrated
        ? { value: 'Checking…', tone: 'neutral' as const }
        : localAvailable
          ? { value: 'Reachable', tone: 'ok' as const }
          : {
              value: local.some(
                (model) =>
                  model.status === 'ollama_unreachable' ||
                  model.status === 'provider_unreachable',
              )
                ? 'Unreachable'
                : 'Unavailable',
              tone: 'error' as const,
            },
      activeModel: activeLocal?.loaded_model?.model ?? activeLocal?.loaded_model?.name ?? 'None',
    }
  }, [agentsStatus, agentsStatusHydrated])

  if (!open) {
    return null
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-md transition-opacity duration-300 motion-reduce:transition-none sm:p-6"
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        ref={dialogRef}
        className="relative flex max-h-[min(88vh,720px)] w-full max-w-xl flex-col rounded-2xl border border-white/10 hud-glass p-5 shadow-2xl outline-none transition-all duration-300 motion-reduce:transition-none sm:p-6"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleDialogKeyDown}
      >
        <header className="mb-4 flex shrink-0 items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="inline-flex size-8 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-[color:var(--hud-accent)]">
              <Settings className="size-4" strokeWidth={2} aria-hidden="true" />
            </span>
            <h2
              id={titleId}
              className="font-orbitron text-sm font-semibold tracking-[0.12em] text-[color:var(--hud-text)]"
            >
              Runtime Settings
            </h2>
          </div>
          <button
            type="button"
            onClick={requestClose}
            className="inline-flex items-center justify-center rounded-lg border border-white/10 bg-white/5 p-1.5 text-[color:var(--hud-text)] transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            aria-label="Close settings"
          >
            <X className="size-4" strokeWidth={2} />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1 scrollbar-thin">
          {loadStatus === 'loading' || loadStatus === 'idle' ? (
            <div className="space-y-2 py-6" aria-busy="true" aria-live="polite">
              <div className="h-3 w-full animate-pulse rounded bg-white/5" />
              <div className="h-3 w-5/6 animate-pulse rounded bg-white/5" />
              <div className="h-3 w-4/5 animate-pulse rounded bg-white/5" />
            </div>
          ) : null}

          {loadStatus === 'error' ? (
            <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200" role="alert">
              {loadError ?? 'Failed to load settings.'}
            </p>
          ) : null}

          {loadStatus === 'ready' && draft ? (
            <>
              <section className="space-y-2.5" aria-labelledby={`${titleId}-data`}>
                <SectionHeading id={`${titleId}-data`} title="Data Sources" />
                <div className="space-y-2">
                  {FEATURE_CONTROLS.map((control) => (
                    <div key={control.key} className="space-y-2">
                      <SettingsToggle
                        id={`settings-feature-${control.key}`}
                        label={control.label}
                        checked={draft.features[control.key]}
                        timing={control.key === 'market' ? marketTiming : featuresTiming}
                        onChange={(next) =>
                          setDraft((prev) => ({
                            ...prev,
                            features: { ...prev.features, [control.key]: next },
                          }))
                        }
                      />
                      {control.key === 'sports' ? (
                        <div className="ml-3 space-y-2 border-l border-white/10 pl-3">
                          {MODULE_CONTROLS.map((module) => (
                            <div key={module.key} className="space-y-2">
                              <SettingsToggle
                                id={`settings-module-${module.key}`}
                                label={module.label}
                                checked={draft.modules[module.key]}
                                disabled={!draft.features.sports}
                                timing={modulesTiming}
                                onChange={(next) =>
                                  setDraft((prev) => ({
                                    ...prev,
                                    modules: { ...prev.modules, [module.key]: next },
                                  }))
                                }
                              />
                              {module.key === 'football' ? (
                                <FootballTeamsEditor
                                  teams={draft.football.teams}
                                  disabled={!draft.features.sports || !draft.modules.football}
                                  onChange={(teams) =>
                                    setDraft((prev) => ({
                                      ...prev,
                                      football: { teams },
                                    }))
                                  }
                                />
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {control.key === 'market' ? (
                        <div className="ml-3 border-l border-white/10 pl-3">
                          <MarketSymbolsEditor
                            symbols={draft.market.symbols}
                            disabled={!draft.features.market}
                            onChange={(symbols) =>
                              setDraft((prev) => ({
                                ...prev,
                                market: { symbols },
                              }))
                            }
                          />
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </section>

              <section className="space-y-2.5" aria-labelledby={`${titleId}-personalization`}>
                <SectionHeading id={`${titleId}-personalization`} title="Personalization" />
                <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2.5">
                  <label
                    htmlFor="settings-user-designation"
                    className="text-xs tracking-wide text-[color:var(--hud-text)]"
                  >
                    User designation
                  </label>
                  <input
                    id="settings-user-designation"
                    type="text"
                    value={draft.user_designation}
                    maxLength={80}
                    placeholder="Optional"
                    aria-describedby={`${titleId}-designation-help`}
                    onChange={(event) =>
                      setDraft((prev) => ({
                        ...prev,
                        user_designation: event.target.value,
                      }))
                    }
                    className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
                  />
                  <p
                    id={`${titleId}-designation-help`}
                    className="mt-1.5 text-[11px] leading-relaxed text-zinc-500"
                  >
                    Optional. APEX uses it when addressing you in future requests and briefings.
                  </p>
                </div>
              </section>

              <section className="space-y-2.5" aria-labelledby={`${titleId}-agent-queries`}>
                <SectionHeading id={`${titleId}-agent-queries`} title="Agent queries" />
                <div className="space-y-2">
                  <SettingsToggle
                    id="settings-agent-queries-enabled"
                    label="Agent queries enabled"
                    checked={draft.ask_apex.enabled}
                    timing={agentQueriesTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        ask_apex: { ...prev.ask_apex, enabled: next },
                      }))
                    }
                  />
                </div>
              </section>

              <section className="space-y-2.5" aria-labelledby={`${titleId}-llama-cpp`}>
                <SectionHeading id={`${titleId}-llama-cpp`} title="llama.cpp" />
                <div className="space-y-2">
                  <SettingsToggle
                    id="settings-llama-cpp-enabled"
                    label="Enable llama.cpp"
                    checked={draft.llama_cpp.enabled}
                    timing={llamaCppTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        llama_cpp: { ...prev.llama_cpp, enabled: next },
                      }))
                    }
                  />
                  <SettingsToggle
                    id="settings-llama-cpp-managed"
                    label="Manage server automatically"
                    checked={draft.llama_cpp.managed}
                    timing={llamaCppTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        llama_cpp: { ...prev.llama_cpp, managed: next },
                      }))
                    }
                  />
                  <div>
                    <label
                      htmlFor="settings-llama-cpp-host"
                      className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
                    >
                      Router URL
                    </label>
                    <input
                      id="settings-llama-cpp-host"
                      type="url"
                      inputMode="url"
                      value={draft.llama_cpp.host}
                      placeholder="http://127.0.0.1:8080"
                      aria-describedby={`${titleId}-llama-cpp-help`}
                      onChange={(event) =>
                        setDraft((prev) => ({
                          ...prev,
                          llama_cpp: { ...prev.llama_cpp, host: event.target.value },
                        }))
                      }
                      className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
                    />
                    <p
                      id={`${titleId}-llama-cpp-help`}
                      className="mt-1.5 text-[11px] leading-relaxed text-zinc-500"
                    >
                      External mode uses a loopback router you start yourself. Managed mode
                      starts your installed llama-server when the router is unreachable.
                      APEX does not install llama.cpp or download model weights.
                    </p>
                  </div>
                  {draft.llama_cpp.managed ? (
                    <>
                      <div>
                        <label
                          htmlFor="settings-llama-cpp-executable"
                          className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
                        >
                          Executable path
                        </label>
                        <input
                          id="settings-llama-cpp-executable"
                          type="text"
                          value={draft.llama_cpp.executable_path}
                          placeholder="C:\path\to\llama-server.exe"
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              llama_cpp: {
                                ...prev.llama_cpp,
                                executable_path: event.target.value,
                              },
                            }))
                          }
                          className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
                        />
                      </div>
                      <div>
                        <label
                          htmlFor="settings-llama-cpp-preset"
                          className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
                        >
                          Preset path
                        </label>
                        <input
                          id="settings-llama-cpp-preset"
                          type="text"
                          value={draft.llama_cpp.preset_path}
                          placeholder="C:\path\to\llama-cpp-apex-local-models.preset.ini"
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              llama_cpp: {
                                ...prev.llama_cpp,
                                preset_path: event.target.value,
                              },
                            }))
                          }
                          className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
                        />
                      </div>
                    </>
                  ) : null}
                  <StatusRow
                    label="Server"
                    value={describeLlamaCppServerStatus(llamaCppRuntime)}
                  />
                  {llamaCppRuntime.status?.state === 'startup_failed' &&
                  llamaCppRuntime.status.last_error ? (
                    <p className="text-[11px] leading-relaxed text-rose-300/90">
                      {llamaCppRuntime.status.last_error}
                    </p>
                  ) : null}
                </div>
              </section>

              <McpSettingsSection
                sectionId={`${titleId}-mcp`}
                baseline={baseline?.mcp ?? null}
                draft={draft.mcp}
                timing={mcpTiming}
                runtime={mcpRuntime}
                onChange={(updater) =>
                  setDraft((prev) => ({
                    ...prev,
                    mcp: updater(prev.mcp),
                  }))
                }
              />

              <MicrosoftTodoSettingsSection
                sectionId={`${titleId}-microsoft-todo`}
                runtime={microsoftTodoRuntime}
                reminderListId={draft.microsoft_todo.reminder_list_id}
                onReminderListIdChange={(reminder_list_id) =>
                  setDraft((prev) => ({
                    ...prev,
                    microsoft_todo: { ...prev.microsoft_todo, reminder_list_id },
                  }))
                }
              />

              <section className="space-y-2.5" aria-labelledby={`${titleId}-voice`}>
                <SectionHeading id={`${titleId}-voice`} title="Voice" />
                <div className="space-y-2">
                  <SettingsSelect
                    id="settings-voice-mode"
                    label="Mode"
                    value={draft.voice.mode}
                    options={VOICE_MODE_OPTIONS}
                    timing={voiceTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        voice: { ...prev.voice, mode: next },
                      }))
                    }
                  />
                  <SettingsSelect
                    id="settings-voice-engine"
                    label="Engine"
                    value={draft.voice.engine}
                    options={ENGINE_OPTIONS}
                    timing={voiceTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        voice: { ...prev.voice, engine: next },
                      }))
                    }
                  />
                  <SettingsSelect
                    id="settings-voice-gender"
                    label="Gender"
                    value={draft.voice.gender}
                    options={GENDER_OPTIONS}
                    timing={voiceTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        voice: { ...prev.voice, gender: next },
                      }))
                    }
                  />
                </div>
              </section>

              <section className="space-y-2.5" aria-labelledby={`${titleId}-runtime`}>
                <SectionHeading id={`${titleId}-runtime`} title="Runtime Status" />
                <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
                  <StatusRow
                    label="Backend"
                    value="Reachable"
                    tone="ok"
                  />
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
                  <StatusRow label="Active local model" value={providerRows.activeModel} />
                  {FEATURE_CONTROLS.map((control) => {
                    const connectorStatus = resolveConnectorStatus(
                      control.key,
                      baseline?.features[control.key] ?? false,
                      failedConnectors,
                      hasBriefingEvidence,
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
              </section>
            </>
          ) : null}
        </div>

        <footer className="mt-4 flex shrink-0 flex-col gap-2 border-t border-white/10 pt-4">
          {saveError ? (
            <p className="text-[11px] text-red-300" role="alert">
              {saveError}
            </p>
          ) : null}
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={requestClose}
              className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] text-[color:var(--hud-text)] uppercase transition-colors hover:border-white/20 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            >
              Close
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!isDirty || saving || loadStatus !== 'ready'}
              className="rounded-lg border border-[color:var(--hud-accent)]/40 bg-[color:var(--hud-accent)]/20 px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] text-[color:var(--hud-text)] uppercase transition-colors hover:bg-[color:var(--hud-accent)]/30 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
