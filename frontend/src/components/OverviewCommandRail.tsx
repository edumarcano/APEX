import { RefreshCw } from 'lucide-react'
import type { ReactElement } from 'react'

import type { BriefingMode } from '../types/settings'
import type { AgentProfileStatus, AssistantProfile } from '../types/telemetry'

import { AskApexBar } from './AskApexBar'
import { BriefingGenerateControl, BriefingModeSelector } from './BriefingControls'
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
}: OverviewCommandRailProps): ReactElement {
  return (
    <section
      aria-label="Overview command rail"
      data-slot="overview-command-rail"
      className="relative z-20 mt-3 w-full max-w-[40rem] rounded-xl border border-white/10 bg-zinc-950/55 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-xl"
    >
      {!activated ? (
        <div className="flex min-h-10 items-center px-1" data-slot="overview-standby-actions">
          <StandbyActions
            onStartApex={onStartApex}
            onStartWithBriefing={onStartWithBriefing}
            disabled={startDisabled}
          />
        </div>
      ) : askApexEnabled ? (
        <div className="flex flex-col gap-2 border-b border-white/10 pb-2 sm:flex-row sm:items-center" data-slot="overview-assistant-controls">
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
          <AskApexBar
            presentation="overview"
            activeProfile={activeProfile}
            onSubmit={onAssistantSubmit}
            profilesStatus={profilesStatus}
            isSubmitting={isAssistantQuerying}
          />
        </div>
      ) : null}

      <div className={`flex flex-wrap items-center gap-2 px-1 ${activated && askApexEnabled ? 'pt-2' : ''}`} data-slot="overview-briefing-controls">
        <BriefingModeSelector
          value={briefingMode}
          onChange={onBriefingModeChange}
          profiles={profilesStatus}
          hydrated={profilesStatusHydrated}
          disabled={briefingControlsBusy}
        />
        {activated ? <>
          <button
            type="button"
            onClick={onRefreshAll}
            disabled={isRefreshingAll}
            data-slot="refresh-all-trigger"
            className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-white/10 bg-black/25 px-3 font-orbitron text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-200 transition-colors hover:border-white/25 hover:bg-white/[0.05] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8] disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Refresh all telemetry"
          >
            <RefreshCw className={`size-3.5 ${isRefreshingAll ? 'animate-spin' : ''}`} aria-hidden />
            {isRefreshingAll ? 'Refreshing' : 'Refresh'}
          </button>
          <BriefingGenerateControl
            mainDisabled={briefingControlsBusy || !briefingModeAvailable || !hasSnapshot}
            refreshDisabled={briefingControlsBusy || !briefingModeAvailable}
            busy={briefingControlsBusy}
            onGenerate={onGenerateBriefing}
            onRefreshAndGenerate={onRefreshAllAndGenerate}
          />
        </> : null}
      </div>
    </section>
  )
}
