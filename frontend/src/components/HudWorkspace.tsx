import type { ComponentProps, ReactElement } from 'react'

import type { BriefingView as BriefingViewComponent, BriefingViewConversation } from './briefing/BriefingView'
import type { BriefingProfilePanelProps } from './briefing/BriefingProfilePanel'
import type { BriefingSpeechControlProps } from './briefing/BriefingSpeechControl'
import type { HudIdentityProps } from './overview/HudIdentity'
import { OverviewView } from './overview/OverviewView'
import type { HudTelemetryData } from './overview/HudTelemetry'
import { CollectTelemetryButton } from './CollectTelemetryButton'
import type { BriefingLayoutPhase, WorkspacePresentationView } from '../hooks/useWorkspaceView'
import type { BriefingTelemetryCollectionState } from './overview/HudTelemetryRail'
import { DeferredPresentation } from './DeferredPresentation'
import { DeferredWorkspaceError, DeferredWorkspaceLoading } from './DeferredWorkspaceState'

type BriefingViewProps = ComponentProps<typeof BriefingViewComponent>

const loadBriefingView = () => import('./briefing/BriefingView').then((module) => ({ default: module.BriefingView }))
const loadBriefingSpeechControl = () => import('./briefing/BriefingSpeechControl').then((module) => ({ default: module.BriefingSpeechControl }))

export type HudWorkspaceProps = {
  view: WorkspacePresentationView
  briefingPhase: BriefingLayoutPhase
  identity: HudIdentityProps
  telemetry: HudTelemetryData
  overviewState: 'center' | 'collecting' | 'ready' | 'error' | 'no-data'
  overviewError?: string | null
  onRefreshAll: () => void
  onOverviewSetupBriefing: () => void
  overviewActions: ComponentProps<typeof CollectTelemetryButton>
  briefingControls: Omit<BriefingProfilePanelProps, 'speechControl'> & { speechControl?: BriefingSpeechControlProps | null }
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
        onSetUpBriefing={props.onOverviewSetupBriefing}
        collectDisabled={props.overviewActions.disabled}
      />
    ) : (
      <DeferredPresentation
        key="briefing"
        load={loadBriefingView}
        componentProps={{
          phase: props.briefingPhase,
          identity: props.identity,
          telemetry: props.telemetry,
          controls: {
            ...props.briefingControls,
            speechControl: props.briefingControls.speechControl ? <DeferredPresentation
              load={loadBriefingSpeechControl}
              componentProps={props.briefingControls.speechControl}
              fallback={<span role="status" className="text-xs text-zinc-400">Loading speech controls…</span>}
              renderError={(retry) => <span role="alert" className="inline-flex flex-wrap items-center gap-2 text-xs text-red-300">Speech controls could not load. <button type="button" onClick={retry} className="underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2">Retry</button><button type="button" onClick={() => { if (window.confirm('Reload APEX? Reloading will discard unsent text.')) window.location.reload() }} className="underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2">Reload APEX</button></span>}
            /> : null,
          },
          conversation: props.briefingConversation,
          telemetryCollection: props.briefingTelemetry,
        } satisfies BriefingViewProps}
        fallback={<DeferredWorkspaceLoading label="Briefing" />}
        renderError={(retry) => <DeferredWorkspaceError label="Briefing" retry={retry} />}
      />
    )}
  </div>
}
