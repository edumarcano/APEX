import type { ReactElement } from 'react'
import { Calendar, CloudSun, LineChart, Trophy } from 'lucide-react'

import CalendarSettingsSection from '../CalendarSettingsSection'
import { FootballTeamsEditor, MarketSymbolsEditor } from '../SettingsListEditors'
import { SettingsCard, SettingsToggle } from '../SettingsControls'
import type { RuntimeSettings, SettingsEffectiveTiming } from '../../types/settings'

interface DataSourcesViewProps {
  titleId: string
  draft: RuntimeSettings
  setDraft: (updater: (prev: RuntimeSettings) => RuntimeSettings) => void
  featuresTiming: SettingsEffectiveTiming
  marketTiming: SettingsEffectiveTiming
  calendarTiming: SettingsEffectiveTiming
  modulesTiming: SettingsEffectiveTiming
}

export default function DataSourcesView({
  titleId,
  draft,
  setDraft,
  featuresTiming,
  marketTiming,
  calendarTiming,
  modulesTiming,
}: DataSourcesViewProps): ReactElement {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Core Feeds Card */}
      <SettingsCard
        id={`${titleId}-feeds`}
        title="Core Feeds"
        icon={CloudSun}
        badgeText="Weather · News · Email"
      >
        <div className="space-y-2">
          <SettingsToggle
            id="settings-feature-weather"
            label="Weather"
            checked={draft.features.weather}
            timing={featuresTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                features: { ...prev.features, weather: next },
              }))
            }
          />
          <SettingsToggle
            id="settings-feature-news"
            label="News"
            checked={draft.features.news}
            timing={featuresTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                features: { ...prev.features, news: next },
              }))
            }
          />
          <SettingsToggle
            id="settings-feature-email"
            label="Email"
            checked={draft.features.email}
            timing={featuresTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                features: { ...prev.features, email: next },
              }))
            }
          />
        </div>
      </SettingsCard>

      {/* Markets Card */}
      <SettingsCard
        id={`${titleId}-markets`}
        title="Markets"
        icon={LineChart}
        timing={marketTiming}
      >
        <div className="space-y-3">
          <SettingsToggle
            id="settings-feature-market"
            label="Market"
            checked={draft.features.market}
            timing={marketTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                features: { ...prev.features, market: next },
              }))
            }
          />
          <div className="border-t border-white/5 pt-2">
            <MarketSymbolsEditor
              symbols={draft.market.symbols}
              disabled={!draft.features.market}
              onChange={(symbols) =>
                setDraft((prev) => ({
                  ...prev,
                  market: { symbols },
                }))
              }
            />
          </div>
        </div>
      </SettingsCard>

      {/* Sports & Competitions Card */}
      <SettingsCard
        id={`${titleId}-sports`}
        title="Sports"
        icon={Trophy}
        timing={featuresTiming}
      >
        <div className="space-y-3">
          <SettingsToggle
            id="settings-feature-sports"
            label="Sports"
            checked={draft.features.sports}
            timing={featuresTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                features: { ...prev.features, sports: next },
              }))
            }
          />

          <div
            className={`space-y-2.5 rounded-lg border border-white/5 bg-white/[0.015] p-3 transition-opacity ${
              !draft.features.sports ? 'opacity-50' : ''
            }`}
          >
            <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-zinc-500">
              Active Leagues & Teams
            </div>
            <SettingsToggle
              id="settings-module-f1"
              label="Formula 1"
              checked={draft.modules.f1}
              disabled={!draft.features.sports}
              timing={modulesTiming}
              onChange={(next) =>
                setDraft((prev) => ({
                  ...prev,
                  modules: { ...prev.modules, f1: next },
                }))
              }
            />
            <SettingsToggle
              id="settings-module-football"
              label="Football"
              checked={draft.modules.football}
              disabled={!draft.features.sports}
              timing={modulesTiming}
              onChange={(next) =>
                setDraft((prev) => ({
                  ...prev,
                  modules: { ...prev.modules, football: next },
                }))
              }
            />
            <div className="border-t border-white/5 pt-2">
              <FootballTeamsEditor
                teams={draft.football.teams}
                disabled={!draft.features.sports || !draft.modules.football}
                onChange={(teams) =>
                  setDraft((prev) => ({
                    ...prev,
                    football: { teams },
                  }))
                }
              />
            </div>
          </div>
        </div>
      </SettingsCard>

      {/* Calendar Card */}
      <SettingsCard
        id={`${titleId}-calendar`}
        title="Calendar"
        icon={Calendar}
        timing={calendarTiming}
      >
        <div className="space-y-3">
          <SettingsToggle
            id="settings-feature-calendar"
            label="Calendar"
            checked={draft.features.calendar}
            timing={calendarTiming}
            onChange={(next) =>
              setDraft((prev) => ({
                ...prev,
                features: { ...prev.features, calendar: next },
              }))
            }
          />
          <div className="border-t border-white/5 pt-2">
            <CalendarSettingsSection
              sectionId={`${titleId}-calendar-section`}
              enabled={draft.features.calendar}
              settings={draft.calendar}
              timing={calendarTiming}
              onChange={(calendar) =>
                setDraft((prev) => ({ ...prev, calendar }))
              }
            />
          </div>
        </div>
      </SettingsCard>
    </div>
  )
}
