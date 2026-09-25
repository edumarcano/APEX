import type { ReactElement } from 'react'

import type {
  AgentKey,
  ToolCatalog,
  ToolPreflightEstimate,
  ModelCatalogEntry,
} from '../types/telemetry'

import { AgentQueryBar } from './AgentQueryBar'
import { LocalModelControl } from './LocalModelControl'
import { StandbyActions } from './StandbyActions'

interface HomeCommandRailProps {
  activated: boolean
  agentQueriesEnabled: boolean
  selectedModelId: string
  onModelChange: (modelId: string) => void
  modelCatalog: ModelCatalogEntry[]
  isCortexQuerying: boolean
  onAgentSubmit: (
    query: string,
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
  dailySessionsCount: number
  dailyBusy: boolean
  hasActiveDailySession: boolean
  canGenerateDaily: boolean
  onGenerateDaily: () => void
  onOpenDailySessions: () => void
  activeLocalModel: ModelCatalogEntry | null
  loadingLocalModel: ModelCatalogEntry | null
  localLifecycleBusy: boolean
  onUnloadLocalModel: () => Promise<boolean>
}

export function HomeCommandRail({
  activated,
  agentQueriesEnabled,
  selectedModelId,
  onModelChange,
  modelCatalog,
  isCortexQuerying,
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
  dailySessionsCount,
  dailyBusy,
  hasActiveDailySession,
  canGenerateDaily,
  onGenerateDaily,
  onOpenDailySessions,
  activeLocalModel,
  loadingLocalModel,
  localLifecycleBusy,
  onUnloadLocalModel,
}: HomeCommandRailProps): ReactElement {
  const showAgentControls = activated && agentQueriesEnabled
  const inferredAgent: AgentKey = 'apex'

  return (
    <section
      className="w-full max-w-[42rem] min-w-0 rounded-xl border border-white/10 bg-zinc-950/55 p-2.5 backdrop-blur-md"
      data-slot="home-command-rail"
      aria-label="Home command rail"
    >
      {!activated ? (
        <div className="grid grid-cols-2 items-center gap-2" data-slot="home-standby-controls">
          <div className="col-span-2 flex min-h-10 justify-center" data-slot="home-standby-actions">
            <StandbyActions
              onStartApex={onStartApex}
              onStartWithBriefing={onStartWithBriefing}
              disabled={startDisabled}
              briefingDisabled={!canGenerateDaily || hasActiveDailySession || dailyBusy}
            />
          </div>

          <LocalModelControl
            model={activeLocalModel}
            loadingModel={loadingLocalModel}
            busy={localLifecycleBusy}
            onUnload={onUnloadLocalModel}
            presentation="rail"
            className="col-span-2 justify-self-center w-full max-w-[20rem]"
          />
        </div>
      ) : (
        <div className={`home-command-grid ${showAgentControls ? 'home-command-grid--with-agent' : 'home-command-grid--briefing-only'}`} data-slot="home-active-controls">
          {showAgentControls ? <>
            <div className="home-command-grid__agent-row" data-slot="home-agent-row">
              <div className="home-command-grid__agent-composer min-w-0 w-full" data-slot="home-agent-composer">
                <AgentQueryBar
                  presentation="home"
                  activeAgent={inferredAgent}
                  onSubmit={(query, _agent, tools, profileId) => onAgentSubmit(query, tools, profileId)}
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
                  selectedModelId={selectedModelId}
                  onModelChange={onModelChange}
                  modelCatalog={modelCatalog}
                />
              </div>
            </div>
          </> : null}
          <div className="home-command-grid__briefing-row" data-slot="home-briefing-row">
            <div className="home-command-grid__briefing min-w-0">
              <p className="font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-amber-100">Daily</p>
              <p className="mt-0.5 text-[9px] text-zinc-500">A concise view of current information and evidence</p>
            </div>
            <div className="home-command-grid__briefing-actions" data-slot="home-briefing-actions">
              <button type="button" onClick={onOpenDailySessions} className="h-10 whitespace-nowrap rounded-lg border border-white/10 px-2.5 font-mono text-[10px] text-zinc-300 hover:border-white/20 hover:text-white" aria-label="Open saved Daily sessions">Saved Daily{dailySessionsCount > 0 ? ' (' + dailySessionsCount + ')' : ''}</button>
              <button type="button" onClick={onGenerateDaily} disabled={!canGenerateDaily || dailyBusy || hasActiveDailySession} className="home-command-grid__synthesize h-10 whitespace-nowrap rounded-lg border border-amber-400/30 bg-amber-950/20 px-3 font-orbitron text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-100 hover:bg-amber-400/15 disabled:cursor-not-allowed disabled:opacity-40">{dailyBusy ? 'Preparing…' : 'Prepare Daily'}</button>
            </div>
          </div>
          <LocalModelControl
            model={activeLocalModel}
            loadingModel={loadingLocalModel}
            busy={localLifecycleBusy}
            onUnload={onUnloadLocalModel}
            presentation="rail"
          />
        </div>
      )}
    </section>
  )
}
