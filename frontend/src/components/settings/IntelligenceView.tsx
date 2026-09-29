import type { ReactElement } from 'react'
import { Cpu, MessageSquare, User } from 'lucide-react'

import { describeLlamaCppServerStatus } from './settingsCategories'
import { SettingsCard, SettingsToggle, StatusRow } from '../SettingsControls'
import type { useLlamaCppStatus } from '../../hooks/useLlamaCppStatus'
import type { RuntimeSettings, SettingsEffectiveTiming } from '../../types/settings'

interface IntelligenceViewProps {
  titleId: string
  draft: RuntimeSettings
  setDraft: (updater: (prev: RuntimeSettings) => RuntimeSettings) => void
  agentQueriesTiming: SettingsEffectiveTiming
  llamaCppTiming: SettingsEffectiveTiming
  llamaCppRuntime: ReturnType<typeof useLlamaCppStatus>
}

export default function IntelligenceView({
  titleId,
  draft,
  setDraft,
  agentQueriesTiming,
  llamaCppTiming,
  llamaCppRuntime,
}: IntelligenceViewProps): ReactElement {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Personalization Card */}
      <SettingsCard
        id={`${titleId}-personalization`}
        title="Personalization"
        icon={User}
        badgeText="Identity & Persona"
      >
        <div className="space-y-3">
          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
            <label
              htmlFor="settings-user-designation"
              className="text-xs tracking-wide text-[color:var(--hud-text)]"
            >
              User designation
            </label>
            <input
              id="settings-user-designation"
              type="text"
              value={draft.user_designation}
              maxLength={80}
              placeholder="Optional"
              aria-describedby={`${titleId}-designation-help`}
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  user_designation: event.target.value,
                }))
              }
              className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            />
            <p
              id={`${titleId}-designation-help`}
              className="mt-1.5 text-[11px] leading-relaxed text-zinc-500"
            >
              Optional. APEX uses it when addressing you in future requests and briefings.
            </p>
          </div>

          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
            <label
              htmlFor="settings-agent-display-name"
              className="text-xs tracking-wide text-[color:var(--hud-text)]"
            >
              Agent name
            </label>
            <input
              id="settings-agent-display-name"
              type="text"
              value={draft.agent_display_name}
              maxLength={80}
              placeholder="Lynx"
              aria-describedby={`${titleId}-agent-name-help`}
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  agent_display_name: event.target.value,
                }))
              }
              className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            />
            <p
              id={`${titleId}-agent-name-help`}
              className="mt-1.5 text-[11px] leading-relaxed text-zinc-500"
            >
              Optional local name for the APEX Agent in Cortex, the CLI, and assistant replies. Leave blank for Lynx.
            </p>
          </div>
        </div>
      </SettingsCard>

      {/* Agent Queries Card */}
      <SettingsCard
        id={`${titleId}-agent-queries`}
        title="Agent queries"
        icon={MessageSquare}
        timing={agentQueriesTiming}
        badgeText="Ask APEX"
      >
        <div className="space-y-3">
          <SettingsToggle
            id="settings-agent-queries-enabled"
            label="Agent queries enabled"
            checked={draft.ask_apex.enabled}
            timing={agentQueriesTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                ask_apex: { ...prev.ask_apex, enabled: next },
              }))
            }
          />
          <p className="text-[11px] leading-relaxed text-zinc-500">
            Enables natural-language operational queries and reasoning tasks powered by configured AI model runtimes.
          </p>
        </div>
      </SettingsCard>

      {/* llama.cpp Local Runner Card */}
      <SettingsCard
        id={`${titleId}-llama-cpp`}
        title="llama.cpp"
        icon={Cpu}
        timing={llamaCppTiming}
        badgeText="Local Runner"
        className="lg:col-span-2"
      >
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <SettingsToggle
              id="settings-llama-cpp-enabled"
              label="Enable llama.cpp"
              checked={draft.llama_cpp.enabled}
              timing={llamaCppTiming}
              onChange={(next) =>
                setDraft((prev) => ({
                  ...prev,
                  llama_cpp: { ...prev.llama_cpp, enabled: next },
                }))
              }
            />
            <SettingsToggle
              id="settings-llama-cpp-managed"
              label="Manage server automatically"
              checked={draft.llama_cpp.managed}
              timing={llamaCppTiming}
              onChange={(next) =>
                setDraft((prev) => ({
                  ...prev,
                  llama_cpp: { ...prev.llama_cpp, managed: next },
                }))
              }
            />
          </div>

          <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
            <label
              htmlFor="settings-llama-cpp-host"
              className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
            >
              Router URL
            </label>
            <input
              id="settings-llama-cpp-host"
              type="url"
              inputMode="url"
              value={draft.llama_cpp.host}
              placeholder="http://127.0.0.1:8080"
              aria-describedby={`${titleId}-llama-cpp-help`}
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  llama_cpp: { ...prev.llama_cpp, host: event.target.value },
                }))
              }
              className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
            />
            <p
              id={`${titleId}-llama-cpp-help`}
              className="mt-1.5 text-[11px] leading-relaxed text-zinc-500"
            >
              External mode uses a loopback router you start yourself. Managed mode
              starts your installed llama-server when the router is unreachable.
              APEX does not install llama.cpp or download model weights.
            </p>
          </div>

          {draft.llama_cpp.managed ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                <label
                  htmlFor="settings-llama-cpp-executable"
                  className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
                >
                  Executable path
                </label>
                <input
                  id="settings-llama-cpp-executable"
                  type="text"
                  value={draft.llama_cpp.executable_path}
                  placeholder="C:\path\to\llama-server.exe"
                  onChange={(event) =>
                    setDraft((prev) => ({
                      ...prev,
                      llama_cpp: {
                        ...prev.llama_cpp,
                        executable_path: event.target.value,
                      },
                    }))
                  }
                  className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
                />
              </div>
              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                <label
                  htmlFor="settings-llama-cpp-preset"
                  className="font-orbitron text-[10px] uppercase tracking-[0.16em] text-zinc-500"
                >
                  Preset path
                </label>
                <input
                  id="settings-llama-cpp-preset"
                  type="text"
                  value={draft.llama_cpp.preset_path}
                  placeholder="C:\path\to\llama-cpp-apex-local-models.preset.ini"
                  onChange={(event) =>
                    setDraft((prev) => ({
                      ...prev,
                      llama_cpp: {
                        ...prev.llama_cpp,
                        preset_path: event.target.value,
                      },
                    }))
                  }
                  className="hud-command-surface mt-1.5 w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)]"
                />
              </div>
            </div>
          ) : null}

          <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-1">
            <StatusRow
              label="Server"
              value={describeLlamaCppServerStatus(llamaCppRuntime)}
            />
            {llamaCppRuntime.status?.state === 'startup_failed' &&
            llamaCppRuntime.status.last_error ? (
              <p className="py-1 text-[11px] leading-relaxed text-rose-300/90">
                {llamaCppRuntime.status.last_error}
              </p>
            ) : null}
          </div>
        </div>
      </SettingsCard>
    </div>
  )
}
