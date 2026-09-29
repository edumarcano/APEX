import type { ReactElement } from 'react'
import { Folder } from 'lucide-react'

import McpSettingsSection from '../McpSettingsSection'
import MicrosoftTodoSettingsSection from '../MicrosoftTodoSettingsSection'
import { SettingsCard, SettingsToggle, StatusRow } from '../SettingsControls'
import type { McpStatusState } from '../../hooks/useMcpStatus'
import type { useMicrosoftTodoStatus } from '../../hooks/useMicrosoftTodoStatus'
import type { useActivityReportFolderStatus } from '../../hooks/useActivityReportFolderStatus'
import type { RuntimeSettings, SettingsEffectiveTiming } from '../../types/settings'

interface IntegrationsViewProps {
  titleId: string
  baseline: RuntimeSettings | null
  draft: RuntimeSettings
  setDraft: (updater: (prev: RuntimeSettings) => RuntimeSettings) => void
  mcpTiming: SettingsEffectiveTiming
  mcpRuntime: McpStatusState
  microsoftTodoRuntime: ReturnType<typeof useMicrosoftTodoStatus>
  reportFolderStatusMessage: string
  reportFolderStatus: ReturnType<typeof useActivityReportFolderStatus>['status']
}

export default function IntegrationsView({
  titleId,
  baseline,
  draft,
  setDraft,
  mcpTiming,
  mcpRuntime,
  microsoftTodoRuntime,
  reportFolderStatusMessage,
  reportFolderStatus,
}: IntegrationsViewProps): ReactElement {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Model Context Protocol Card */}
      <div className="hud-corner-brackets hud-glass relative flex flex-col rounded-xl border border-white/10 bg-white/[0.02] p-4 lg:col-span-2">
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />
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
      </div>

      {/* Microsoft To Do Card */}
      <div className="hud-corner-brackets hud-glass relative flex flex-col rounded-xl border border-white/10 bg-white/[0.02] p-4">
        <span className="hud-corner-bl" aria-hidden />
        <span className="hud-corner-br" aria-hidden />
        <MicrosoftTodoSettingsSection
          sectionId={`${titleId}-microsoft-todo`}
          runtime={microsoftTodoRuntime}
          reminderListId={draft.microsoft_todo.reminder_list_id}
          onReminderListIdChange={(reminder_list_id) =>
            setDraft((prev) => ({
              ...prev,
              microsoft_todo: { ...prev.microsoft_todo, reminder_list_id },
            }))
          }
        />
      </div>

      {/* Local Report Folder Card */}
      <SettingsCard
        id={`${titleId}-activity-report-folder`}
        title="Local report folder"
        icon={Folder}
        badgeText="Activity Ingestion"
      >
        <div className="space-y-3">
          <SettingsToggle
            id="settings-activity-report-folder-enabled"
            label="Enable report folder"
            checked={draft.activity_report_folder.enabled}
            timing="Active"
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                activity_report_folder: {
                  ...prev.activity_report_folder,
                  enabled: next,
                },
              }))
            }
          />
          <div>
            <label
              htmlFor="settings-activity-report-folder-path"
              className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
            >
              Absolute folder path
            </label>
            <input
              id="settings-activity-report-folder-path"
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={draft.activity_report_folder.folder_path}
              placeholder="C:\\Users\\you\\AppData\\Local\\APEX\\activity-report-folder"
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  activity_report_folder: {
                    ...prev.activity_report_folder,
                    folder_path: event.target.value,
                  },
                }))
              }
              className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            />
          </div>
          <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
            <StatusRow
              label="Report folder"
              value={reportFolderStatusMessage}
              tone={
                reportFolderStatus?.state === 'ready'
                  ? 'ok'
                  : reportFolderStatus?.state === 'disabled'
                    ? 'neutral'
                    : 'warn'
              }
            />
          </div>
          <p className="text-[11px] leading-relaxed text-zinc-500">
            APEX polls this folder every minute and leaves files untouched. Place each completed version-one {`{"client_id":"source-id","report":{...}}`} envelope in a top-level .json file. The source ID is claimed attribution, not authentication.
          </p>
        </div>
      </SettingsCard>
    </div>
  )
}
