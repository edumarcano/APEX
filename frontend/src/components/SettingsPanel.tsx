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
import {
  SectionHeading,
  SettingsSelect,
  SettingsToggle,
  StatusRow,
} from './SettingsControls'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useMcpStatus } from '../hooks/useMcpStatus'
import { useMicrosoftTodoStatus } from '../hooks/useMicrosoftTodoStatus'
import { useSettingsEditor } from '../hooks/useSettingsEditor'
import {
  buildSettingsTimingRuntime,
  resolveEffectiveTiming,
} from '../lib/settings'
import type {
  AgentProfileStatus,
  SystemState,
  TtsEngine,
} from '../types/telemetry'
import type {
  BriefingMode,
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

const BRIEFING_MODE_OPTIONS: readonly { value: BriefingMode; label: string }[] = [
  { value: 'panthera', label: 'Panthera — Full briefing · cloud synthesis' },
  { value: 'sorex', label: 'Sorex — Quick briefing · limited telemetry' },
  {
    value: 'mus',
    label: 'Mus — Full briefing · balanced local synthesis (Recommended)',
  },
  {
    value: 'structured_digest',
    label: 'Structured Digest — Structured facts · no model or synthesis',
  },
]

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
  restoreFocusRef?: RefObject<HTMLElement | null>
  status: SystemState
  pipelineStep: number | null
  isSpeaking: boolean
  isAssistantQuerying: boolean
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  failedConnectors: string[]
  hasBriefingEvidence: boolean
  onApplied: (response: SettingsResponse) => void
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

export default function SettingsPanel({
  open,
  onClose,
  restoreFocusRef,
  status,
  pipelineStep,
  isSpeaking,
  isAssistantQuerying,
  profilesStatus,
  profilesStatusHydrated,
  failedConnectors,
  hasBriefingEvidence,
  onApplied,
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
  const mcpRuntime = useMcpStatus(open)

  const microsoftTodoRuntime = useMicrosoftTodoStatus(open)
  useFocusTrap(open, dialogRef, restoreFocusRef)

  const timingRuntime = useMemo(
    () =>
      buildSettingsTimingRuntime({
        status,
        pipelineStep,
        isSpeaking,
        isAssistantQuerying,
      }),
    [status, pipelineStep, isSpeaking, isAssistantQuerying],
  )

  const featuresTiming = resolveEffectiveTiming('features', timingRuntime)
  const marketTiming = resolveEffectiveTiming('market', timingRuntime)
  const modulesTiming = resolveEffectiveTiming('modules', timingRuntime)
  const assistantTiming = resolveEffectiveTiming('assistant', timingRuntime)
  const briefingTiming = resolveEffectiveTiming('briefing', timingRuntime)
  const voiceTiming = resolveEffectiveTiming('voice', timingRuntime)
  const mcpTiming = resolveEffectiveTiming('mcp', timingRuntime)

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
    const cloud = profilesStatus.filter((profile) => profile.mode === 'cloud')
    const local = profilesStatus.filter((profile) => profile.mode === 'local')
    const configuredCloud = cloud.filter((profile) => profile.status !== 'disabled').length
    const verifiedCloud = cloud.filter((profile) => profile.status === 'verified').length
    const localAvailable = local.some((profile) => profile.status === 'available')
    const activeLocal = local.find((profile) => profile.active && profile.loaded_model)

    return {
      cloud: !profilesStatusHydrated
        ? { value: 'Checking…', tone: 'neutral' as const }
        : configuredCloud > 0
          ? { value: `${configuredCloud} configured · ${verifiedCloud} verified`, tone: verifiedCloud > 0 ? 'ok' as const : 'neutral' as const }
          : { value: 'Not configured', tone: 'error' as const },
      local: !profilesStatusHydrated
        ? { value: 'Checking…', tone: 'neutral' as const }
        : localAvailable
          ? { value: 'Reachable', tone: 'ok' as const }
          : {
              value: local.some((p) => p.status === 'ollama_unreachable')
                ? 'Unreachable'
                : 'Unavailable',
              tone: 'error' as const,
            },
      activeModel: activeLocal?.loaded_model?.model ?? activeLocal?.loaded_model?.name ?? 'None',
    }
  }, [profilesStatus, profilesStatusHydrated])

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
                            <SettingsToggle
                              key={module.key}
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
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </section>

              <section className="space-y-2.5" aria-labelledby={`${titleId}-assistant`}>
                <SectionHeading id={`${titleId}-assistant`} title="Assistant" />
                <div className="space-y-2">
                  <SettingsToggle
                    id="settings-assistant-enabled"
                    label="Ask APEX enabled"
                    checked={draft.assistant.enabled}
                    timing={assistantTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        assistant: { ...prev.assistant, enabled: next },
                      }))
                    }
                  />
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
              />

              <section className="space-y-2.5" aria-labelledby={`${titleId}-briefing`}>
                <SectionHeading id={`${titleId}-briefing`} title="Briefing" />
                <div className="space-y-2">
                  <SettingsSelect
                    id="settings-briefing-default-mode"
                    label="Default mode"
                    value={draft.briefing.default_mode}
                    options={BRIEFING_MODE_OPTIONS}
                    timing={briefingTiming}
                    onChange={(next) =>
                      setDraft((prev) => ({
                        ...prev,
                        briefing: { ...prev.briefing, default_mode: next },
                      }))
                    }
                  />
                </div>
              </section>

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
                    label="Cloud profiles"
                    value={providerRows.cloud.value}
                    tone={providerRows.cloud.tone}
                  />
                  <StatusRow
                    label="Local profiles"
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
