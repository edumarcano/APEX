import type { ReactElement } from 'react'

import { BriefingView, type BriefingViewConversation } from './briefing/BriefingView'
import type { BriefingProfilePanelProps } from './briefing/BriefingProfilePanel'
import type { HudIdentityProps } from './overview/HudIdentity'
import { OverviewView } from './overview/OverviewView'
import type { HudTelemetryData } from './overview/HudTelemetry'
import type { ComponentProps } from 'react'
import { StandbyActions } from './StandbyActions'
import type { BriefingLayoutPhase, WorkspacePresentationView } from '../hooks/useWorkspaceView'
import type { BriefingTelemetryCollectionState } from './overview/HudTelemetryRail'

export type HudWorkspaceProps = {
  view: WorkspacePresentationView
  briefingPhase: BriefingLayoutPhase
  identity: HudIdentityProps
  telemetry: HudTelemetryData
  overviewState: 'center' | 'collecting' | 'ready' | 'error' | 'no-data'
  overviewError?: string | null
  onRefreshAll: () => void
  overviewActions: ComponentProps<typeof StandbyActions>
  briefingControls: BriefingProfilePanelProps
  briefingConversation: BriefingViewConversation
  briefingTelemetry: {
    hasUsableSnapshot: boolean
    state: BriefingTelemetryCollectionState
    error: string | null
    disabled: boolean
    onCollect: () => void
  }
}

/** Composes Overview and Briefing workspace presentations. */
export function HudWorkspace(props: HudWorkspaceProps): ReactElement {
  const overviewCentered = props.view === 'overview' &&
    (props.overviewState === 'center' || props.overviewState === 'error' || props.overviewState === 'no-data')
  return <div className={`hud-body-layout flex h-full min-h-0 w-full min-w-0 flex-1 flex-col overflow-visible xl:overflow-hidden ${overviewCentered ? 'hud-body-layout--overview-center' : ''}`}>
    {props.view === 'overview' ? (
      <OverviewView
        identity={props.identity}
        telemetry={props.telemetry}
        state={props.overviewState}
        error={props.overviewError}
        onCollect={props.overviewActions.onCollectTelemetry}
        onRefreshAll={props.onRefreshAll}
        collectDisabled={props.overviewActions.disabled}
      />
    ) : (
      <BriefingView
        phase={props.briefingPhase}
        identity={props.identity}
        telemetry={props.telemetry}
        controls={props.briefingControls}
        conversation={props.briefingConversation}
        telemetryCollection={props.briefingTelemetry}
      />
    )}
  </div>
}
