import type { ReactElement } from 'react'

import type { BriefingMode } from '../types/settings'
import type {
  AgentStatus,
  AgentKey,
  LocalSettingsAgent,
  ToolCatalog,
  ToolPreflightEstimate,
} from '../types/telemetry'

import { AgentQueryBar } from './AgentQueryBar'
import { BriefingGenerateControl, BriefingModeSelector } from './BriefingControls'
import { LocalModelControl } from './LocalModelControl'
import { AgentSelector } from './AgentSelector'
import { StandbyActions } from './StandbyActions'

interface HomeCommandRailProps {
  activated: boolean
  agentQueriesEnabled: boolean
  activeAgent: AgentKey
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  isCortexQuerying: boolean
  verifyingCloudAgent: AgentKey | null
  onAgentChange: (agent: AgentKey) => void
  onVerifyCloudAgent: (agent: Exclude<AgentKey, LocalSettingsAgent>) => Promise<boolean>
  onAgentSubmit: (
    query: string,
    agent: AgentKey,
    selectedToolNames: string[],
    toolProfileId: string | null,
  ) => Promise<boolean>
  toolCatalog?: ToolCatalog | null
  selectedToolNames?: string[]
  activeToolProfileId?: string | null
  selectionReady?: boolean
  submissionPending?: boolean
  onToolSelectionChange?: (names: string[]) => void
  onToolProfileChange?: (profileId: string) => void
  toolPreflight?: ToolPreflightEstimate | null
  toolPreflightLoading?: boolean
  toolCatalogError?: string | null
  toolPreflightError?: string | null
  toolProfileFeedback?: string | null
  toolProfileError?: string | null
  draftPrompt?: string
  onDraftChange?: (value: string) => void
  onSaveToolProfile?: (name: string) => void
  onDuplicateToolProfile?: (profileId: string, name: string) => void
  onRenameToolProfile?: (profileId: string, name: string) => void
  onDeleteToolProfile?: (profileId: string) => void
  onRestoreToolProfile?: (profileId: string) => void
  onSetDefaultToolProfile?: (profileId: string) => void
  onStartApex: () => void
  onStartWithBriefing: () => void
  startDisabled: boolean
  briefingMode: BriefingMode
  onBriefingModeChange: (runtime: BriefingMode) => void
  briefingControlsBusy: boolean
  briefingModeAvailable: boolean
  hasSnapshot: boolean
  isRefreshingAll: boolean
  onRefreshAll: () => void
  onGenerateBriefing: () => void
  onRefreshAllAndGenerate: () => void
  activeLocalModel: AgentStatus | null
  loadingLocalAgent: AgentStatus | null
  localLifecycleBusy: boolean
  onUnloadLocalModel: () => Promise<boolean>
}

export function HomeCommandRail({
  activated,
  agentQueriesEnabled,
  activeAgent,
  agentsStatus,
  agentsStatusHydrated,
  isCortexQuerying,
  verifyingCloudAgent,
  onAgentChange,
  onVerifyCloudAgent,
  onAgentSubmit,
  toolCatalog = null,
  selectedToolNames = [],
  activeToolProfileId = null,
  selectionReady = false,
  submissionPending = false,
  onToolSelectionChange = () => undefined,
  onToolProfileChange = () => undefined,
  toolPreflight = null,
  toolPreflightLoading = false,
  toolCatalogError = null,
  toolPreflightError = null,
  toolProfileFeedback = null,
  toolProfileError = null,
  draftPrompt,
  onDraftChange,
  onSaveToolProfile,
  onDuplicateToolProfile,
  onRenameToolProfile,
  onDeleteToolProfile,
  onRestoreToolProfile,
  onSetDefaultToolProfile,
  onStartApex,
  onStartWithBriefing,
  startDisabled,
  briefingMode,
  onBriefingModeChange,
  briefingControlsBusy,
  briefingModeAvailable,
  hasSnapshot,
  isRefreshingAll,
  onRefreshAll,
  onGenerateBriefing,
  onRefreshAllAndGenerate,
  activeLocalModel,
  loadingLocalAgent,
  localLifecycleBusy,
  onUnloadLocalModel,
}: HomeCommandRailProps): ReactElement {
  const showAgentControls = activated && agentQueriesEnabled
  return (
    <section
      aria-label="Home command rail"
      data-slot="home-command-rail"
      className="relative z-20 mt-3 w-full max-w-[40rem] min-w-0 rounded-xl border border-white/10 bg-zinc-950/55 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-xl"
    >
      {!activated ? (
        <div className="grid grid-cols-2 items-center gap-2" data-slot="home-standby-controls">
          <div className="col-span-2 flex min-h-10 justify-center" data-slot="home-standby-actions">
          <StandbyActions
            onStartApex={onStartApex}
            onStartWithBriefing={onStartWithBriefing}
            disabled={startDisabled}
          />
        </div>
          <BriefingModeSelector
            value={briefingMode}
            onChange={onBriefingModeChange}
            agents={agentsStatus}
            hydrated={agentsStatusHydrated}
            disabled={briefingControlsBusy}
            className="col-span-2 justify-self-center w-full max-w-[20rem]"
          />
        </div>
      ) : (
        <div className={`home-command-grid ${showAgentControls ? 'home-command-grid--with-agent' : 'home-command-grid--briefing-only'}`} data-slot="home-active-controls">
          {showAgentControls ? <>
            <div className="home-command-grid__agent-row" data-slot="home-agent-row">
              <div className="home-command-grid__agent-selector min-w-0" data-slot="home-agent-selector">
                <AgentSelector
                  presentation="home"
                  activeAgent={activeAgent}
                  onChange={onAgentChange}
                  agentsStatus={agentsStatus}
                  agentsStatusHydrated={agentsStatusHydrated}
                  isQuerying={isCortexQuerying || submissionPending}
                  verifyingAgent={verifyingCloudAgent}
                  onVerify={onVerifyCloudAgent}
                />
              </div>
              <div className="home-command-grid__agent-composer min-w-0" data-slot="home-agent-composer">
                <AgentQueryBar
                  presentation="home"
                  activeAgent={activeAgent}
                  onSubmit={onAgentSubmit}
                  agentsStatus={agentsStatus}
                  catalog={toolCatalog}
                  selectedToolNames={selectedToolNames}
                  activeToolProfileId={activeToolProfileId}
                  selectionReady={selectionReady}
                  submissionPending={submissionPending}
                  onToolSelectionChange={onToolSelectionChange}
                  onToolProfileChange={onToolProfileChange}
                  toolPreflight={toolPreflight}
                  toolPreflightLoading={toolPreflightLoading}
                  toolCatalogError={toolCatalogError}
                  toolPreflightError={toolPreflightError}
                  toolProfileFeedback={toolProfileFeedback}
                  toolProfileError={toolProfileError}
                  draftPrompt={draftPrompt}
                  onDraftChange={onDraftChange}
                  onSaveToolProfile={onSaveToolProfile}
                  onDuplicateToolProfile={onDuplicateToolProfile}
                  onRenameToolProfile={onRenameToolProfile}
                  onDeleteToolProfile={onDeleteToolProfile}
                  onRestoreToolProfile={onRestoreToolProfile}
                  onSetDefaultToolProfile={onSetDefaultToolProfile}
                  isSubmitting={isCortexQuerying}
                />
              </div>
            </div>
          </> : null}
          <div className="home-command-grid__briefing-row" data-slot="home-briefing-row">
            <BriefingModeSelector
              value={briefingMode}
              onChange={onBriefingModeChange}
              agents={agentsStatus}
              hydrated={agentsStatusHydrated}
              disabled={briefingControlsBusy}
              className="home-command-grid__briefing min-w-0"
            />
            <div className="home-command-grid__briefing-actions" data-slot="home-briefing-actions">
              <BriefingGenerateControl
                mainDisabled={briefingControlsBusy || !briefingModeAvailable || !hasSnapshot}
                refreshDisabled={briefingControlsBusy || !briefingModeAvailable || isRefreshingAll}
                busy={briefingControlsBusy || isRefreshingAll}
                onGenerate={onGenerateBriefing}
                onRefreshAll={onRefreshAll}
                onRefreshAndGenerate={onRefreshAllAndGenerate}
                className="home-command-grid__synthesize"
              />
            </div>
          </div>
          <LocalModelControl
            agent={activeLocalModel}
            loadingAgent={loadingLocalAgent}
            busy={localLifecycleBusy}
            onUnload={onUnloadLocalModel}
            presentation="rail"
          />
        </div>
      )}
    </section>
  )
}
