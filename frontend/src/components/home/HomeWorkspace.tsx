import type { ReactElement } from 'react'

import type { BriefingLayoutPhase, HomeView } from '../../hooks/useHomeView'
import { HomeBriefing, type HomeBriefingConversation } from './HomeBriefing'
import type { BriefingProfilePanelProps } from './BriefingProfilePanel'
import type { HomeIdentityProps } from './HomeIdentity'
import { HomeOverview } from './HomeOverview'
import { HomeStandby, type HomeStandbyProps } from './HomeStandby'
import type { HomeTelemetryData } from './HomeTelemetry'

export type HomeWorkspaceProps = {
  view: HomeView
  briefingPhase: BriefingLayoutPhase
  identity: HomeIdentityProps
  telemetry: HomeTelemetryData
  standbyActions: HomeStandbyProps['actions']
  briefingControls: BriefingProfilePanelProps
  briefingConversation: HomeBriefingConversation
}

/** Composes the Standby, Overview, and Briefing Home states. */
export function HomeWorkspace(props: HomeWorkspaceProps): ReactElement {
  return <div className="hud-body-layout flex w-full min-w-0 flex-col overflow-visible xl:h-full xl:min-h-0 xl:flex-1 xl:overflow-hidden">
    {props.view === 'standby' ? (
      <HomeStandby identity={props.identity} actions={props.standbyActions} />
    ) : props.view === 'overview' ? (
      <HomeOverview
        identity={props.identity}
        telemetry={props.telemetry}
      />
    ) : (
      <HomeBriefing
        phase={props.briefingPhase}
        identity={props.identity}
        telemetry={props.telemetry}
        controls={props.briefingControls}
        conversation={props.briefingConversation}
      />
    )}
  </div>
}
