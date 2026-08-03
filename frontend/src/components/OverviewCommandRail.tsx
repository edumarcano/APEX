import type { ReactElement } from 'react'

import type { BriefingMode } from '../types/settings'
import type { AgentProfileStatus, AssistantProfile } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'
import { BriefingGenerateControl, BriefingModeSelector } from './BriefingControls'
import { LocalModelControl } from './LocalModelControl'
import { ProfileCardSelector } from './ProfileCardSelector'
import { StandbyActions } from './StandbyActions'

interface OverviewCommandRailProps {
  activated: boolean
  askApexEnabled: boolean
  activeProfile: AssistantProfile
  profilesStatus: AgentProfileStatus[]
  profilesStatusHydrated: boolean
  devModeActive: boolean
  isAssistantQuerying: boolean
  verifyingCloudProfile: AssistantProfile | null
  onProfileChange: (profile: AssistantProfile) => void
  onVerifyCloudProfile: (profile: Exclude<AssistantProfile, 'mus' | 'sorex'>) => Promise<boolean>
  onAssistantSubmit: (query: string, profile: AssistantProfile) => void
  onStartApex: () => void
  onStartWithBriefing: () => void
  startDisabled: boolean
  briefingMode: BriefingMode
  onBriefingModeChange: (mode: BriefingMode) => void
  briefingControlsBusy: boolean
  briefingModeAvailable: boolean
  hasSnapshot: boolean
  isRefreshingAll: boolean
  onRefreshAll: () => void
  onGenerateBriefing: () => void
  onRefreshAllAndGenerate: () => void
  activeLocalModel: AgentProfileStatus | null
  loadingLocalProfile: AgentProfileStatus | null
  localLifecycleBusy: boolean
  onUnloadLocalModel: () => Promise<boolean>
}

export function OverviewCommandRail({
  activated,
  askApexEnabled,
  activeProfile,
  profilesStatus,
  profilesStatusHydrated,
  devModeActive,
  isAssistantQuerying,
  verifyingCloudProfile,
  onProfileChange,
  onVerifyCloudProfile,
  onAssistantSubmit,
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
  loadingLocalProfile,
  localLifecycleBusy,
  onUnloadLocalModel,
}: OverviewCommandRailProps): ReactElement {
  const showAssistantControls = activated && askApexEnabled
  return (
    <section
      aria-label="Overview command rail"
      data-slot="overview-command-rail"
      className="relative z-20 mt-3 w-full max-w-[40rem] rounded-xl border border-white/10 bg-zinc-950/55 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-xl"
    >
      {!activated ? (
        <div className="grid grid-cols-2 items-center gap-2" data-slot="overview-standby-controls">
          <div className="col-span-2 flex min-h-10 justify-center" data-slot="overview-standby-actions">
          <StandbyActions
            onStartApex={onStartApex}
            onStartWithBriefing={onStartWithBriefing}
            disabled={startDisabled}
          />
        </div>
          <BriefingModeSelector
            value={briefingMode}
            onChange={onBriefingModeChange}
            profiles={profilesStatus}
            hydrated={profilesStatusHydrated}
            disabled={briefingControlsBusy}
            className="col-span-2 justify-self-center w-full max-w-[20rem]"
          />
        </div>
      ) : (
        <div className={`overview-command-grid ${showAssistantControls ? 'overview-command-grid--with-assistant' : 'overview-command-grid--briefing-only'}`} data-slot="overview-active-controls">
          {showAssistantControls ? <>
            <div className="overview-command-grid__assistant-row" data-slot="overview-assistant-row">
              <div className="overview-command-grid__assistant-profile min-w-0" data-slot="overview-assistant-profile">
                <ProfileCardSelector
                  presentation="overview"
                  activeProfile={activeProfile}
                  onChange={onProfileChange}
                  profilesStatus={profilesStatus}
                  profilesStatusHydrated={profilesStatusHydrated}
                  devModeActive={devModeActive}
                  isQuerying={isAssistantQuerying}
                  verifyingProfile={verifyingCloudProfile}
                  onVerify={onVerifyCloudProfile}
                />
              </div>
              <div className="overview-command-grid__assistant-composer min-w-0" data-slot="overview-assistant-composer">
                <AskApexBar
                  presentation="overview"
                  activeProfile={activeProfile}
                  onSubmit={onAssistantSubmit}
                  profilesStatus={profilesStatus}
                  isSubmitting={isAssistantQuerying}
                />
              </div>
            </div>
          </> : null}
          <div className="overview-command-grid__briefing-row" data-slot="overview-briefing-row">
            <BriefingModeSelector
              value={briefingMode}
              onChange={onBriefingModeChange}
              profiles={profilesStatus}
              hydrated={profilesStatusHydrated}
              disabled={briefingControlsBusy}
              className="overview-command-grid__briefing min-w-0"
            />
            <div className="overview-command-grid__briefing-actions" data-slot="overview-briefing-actions">
              <LocalModelControl
                profile={activeLocalModel}
                loadingProfile={loadingLocalProfile}
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
                className="overview-command-grid__synthesize"
              />
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
