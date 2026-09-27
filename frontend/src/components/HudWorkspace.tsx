import type { ReactElement } from 'react'

import { BriefingView, type BriefingViewConversation } from './briefing/BriefingView'
import type { BriefingProfilePanelProps } from './briefing/BriefingProfilePanel'
import type { HudIdentityProps } from './overview/HudIdentity'
import { OverviewView } from './overview/OverviewView'
import type { HudTelemetryData } from './overview/HudTelemetry'
import { StandbyView, type StandbyViewProps } from './standby/StandbyView'
import type { BriefingLayoutPhase, WorkspacePresentationView } from '../hooks/useWorkspaceView'

export type HudWorkspaceProps = {
  view: WorkspacePresentationView
  briefingPhase: BriefingLayoutPhase
  identity: HudIdentityProps
  telemetry: HudTelemetryData
  standbyActions: StandbyViewProps['actions']
  briefingControls: BriefingProfilePanelProps
  briefingConversation: BriefingViewConversation
}

/** Composes Standby, Overview, and Briefing peer presentations. */
export function HudWorkspace(props: HudWorkspaceProps): ReactElement {
  return <div className="hud-body-layout flex w-full min-w-0 flex-col overflow-visible xl:h-full xl:min-h-0 xl:flex-1 xl:overflow-hidden">
    {props.view === 'standby' ? (
      <StandbyView identity={props.identity} actions={props.standbyActions} />
    ) : props.view === 'overview' ? (
      <OverviewView
        identity={props.identity}
        telemetry={props.telemetry}
      />
    ) : (
      <BriefingView
        phase={props.briefingPhase}
        identity={props.identity}
        telemetry={props.telemetry}
        controls={props.briefingControls}
        conversation={props.briefingConversation}
      />
    )}
  </div>
}
