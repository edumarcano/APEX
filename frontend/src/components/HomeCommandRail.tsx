import type { ReactElement } from 'react'

import type { BriefingMode } from '../types/settings'
import type { AgentStatus, AgentKey } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'
import { BriefingGenerateControl, BriefingModeSelector } from './BriefingControls'
import { LocalModelControl } from './LocalModelControl'
import { AgentSelector } from './AgentSelector'
import { StandbyActions } from './StandbyActions'

interface HomeCommandRailProps {
  activated: boolean
  askApexEnabled: boolean
  activeAgent: AgentKey
  agentsStatus: AgentStatus[]
  agentsStatusHydrated: boolean
  isCortexQuerying: boolean
  verifyingCloudAgent: AgentKey | null
  onAgentChange: (agent: AgentKey) => void
  onVerifyCloudAgent: (agent: Exclude<AgentKey, 'mus' | 'sorex'>) => Promise<boolean>
  onAgentSubmit: (query: string, agent: AgentKey) => void
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
  askApexEnabled,
  activeAgent,
  agentsStatus,
  agentsStatusHydrated,
  isCortexQuerying,
  verifyingCloudAgent,
  onAgentChange,
  onVerifyCloudAgent,
  onAgentSubmit,
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
  const showAgentControls = activated && askApexEnabled
  return (
    <section
      aria-label="Home command rail"
      data-slot="home-command-rail"
      className="relative z-20 mt-3 w-full max-w-[40rem] rounded-xl border border-white/10 bg-zinc-950/55 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-xl"
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
                  isQuerying={isCortexQuerying}
                  verifyingAgent={verifyingCloudAgent}
                  onVerify={onVerifyCloudAgent}
                />
              </div>
              <div className="home-command-grid__agent-composer min-w-0" data-slot="home-agent-composer">
                <AskApexBar
                  presentation="home"
                  activeAgent={activeAgent}
                  onSubmit={onAgentSubmit}
                  agentsStatus={agentsStatus}
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
              <LocalModelControl
                agent={activeLocalModel}
                loadingAgent={loadingLocalAgent}
                busy={localLifecycleBusy}
                onUnload={onUnloadLocalModel}
                presentation="rail"
              />
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
        </div>
      )}
    </section>
  )
}
