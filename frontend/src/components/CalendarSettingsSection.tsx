import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import { API_ENDPOINTS } from '../lib/api'
import type { CalendarSettings } from '../types/settings'
import type { SettingsEffectiveTiming } from '../types/settings'
import { SectionHeading, SettingsToggle } from './SettingsControls'

const MAX_SELECTED_CALENDARS = 25

interface CalendarChoice {
  id: string
  display_name: string
  primary: boolean
  hidden: boolean
}

function parseChoices(body: unknown): CalendarChoice[] | null {
  if (!body || typeof body !== 'object' || !Array.isArray((body as { calendars?: unknown }).calendars)) return null
  const calendars = (body as { calendars: unknown[] }).calendars.flatMap((entry): CalendarChoice[] => {
    if (!entry || typeof entry !== 'object') return []
    const item = entry as Record<string, unknown>
    if (typeof item.id !== 'string' || !item.id || typeof item.display_name !== 'string' || typeof item.primary !== 'boolean' || typeof item.hidden !== 'boolean') return []
    return [{ id: item.id, display_name: item.display_name, primary: item.primary, hidden: item.hidden }]
  })
  return calendars.length <= 250 ? calendars : null
}

export default function CalendarSettingsSection({
  sectionId,
  enabled,
  settings,
  timing,
  onChange,
}: {
  sectionId: string
  enabled: boolean
  settings: CalendarSettings
  timing: SettingsEffectiveTiming
  onChange: (settings: CalendarSettings) => void
}): ReactElement | null {
  const [choices, setChoices] = useState<CalendarChoice[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requested = useRef(false)

  const load = useCallback(async (): Promise<void> => {
    requested.current = true
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(API_ENDPOINTS.googleCalendarCalendars)
      const parsed = response.ok ? parseChoices(await response.json()) : null
      if (!parsed) throw new Error()
      setChoices(parsed)
    } catch {
      setError('Calendar choices are unavailable. Retry after checking Google Calendar access.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (enabled && !requested.current && !loading) void load()
  }, [enabled, load, loading])

  if (!enabled) return null
  const known = new Set(choices.map((choice) => choice.id))
  const rows = [
    ...settings.selected_calendar_ids.filter((id) => !known.has(id)).map((id) => ({ id, display_name: 'Saved calendar unavailable', primary: false, hidden: false })),
    ...choices,
  ]
  const selected = new Set(settings.selected_calendar_ids)
  const atSelectionLimit = selected.size >= MAX_SELECTED_CALENDARS

  return (
    <div className="ml-3 space-y-2 border-l border-white/10 pl-3">
      <section className="space-y-2.5" aria-labelledby={sectionId}>
        <SectionHeading id={sectionId} title="Calendar selection" />
        <p className="text-[11px] leading-relaxed text-zinc-500">Choose the Google calendars APEX reads. Primary can be unchecked. Saved calendars that are no longer available stay listed until removed.</p>
        <p id={`${sectionId}-selection-limit`} className="text-[11px] text-zinc-500">{selected.size} of {MAX_SELECTED_CALENDARS} calendars selected. Select up to {MAX_SELECTED_CALENDARS}; remove a selected calendar before adding another.</p>
        {loading ? <p className="text-[11px] text-zinc-400" role="status">Loading calendars…</p> : null}
        {error ? <div className="space-y-2"><p className="text-[11px] text-red-300" role="status">{error}</p><button type="button" onClick={() => void load()} className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-zinc-200">Retry</button></div> : null}
        {!loading && !error ? <fieldset className="space-y-1.5" aria-describedby={`${sectionId}-selection-limit`}><legend className="sr-only">Calendars to read</legend>{rows.map((choice) => {
          const isSelected = selected.has(choice.id)
          const selectionBlocked = !isSelected && atSelectionLimit
          return <label key={choice.id} className={`flex items-start gap-2 rounded-md px-1 py-1 text-xs text-zinc-200 ${selectionBlocked ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-white/[0.03]'}`}><input type="checkbox" checked={isSelected} disabled={selectionBlocked} onChange={() => {
          if (selectionBlocked) return
          const next = isSelected ? settings.selected_calendar_ids.filter((id) => id !== choice.id) : [...settings.selected_calendar_ids, choice.id]
          onChange({ ...settings, selected_calendar_ids: next })
        }} className="mt-0.5 size-3.5 accent-[color:var(--hud-accent)]" /><span>{choice.display_name}{choice.primary ? ' · Primary' : ''}{choice.hidden ? ' · Hidden' : ''}</span></label>
        })}</fieldset> : null}
        <SettingsToggle id="settings-calendar-show-names" label="Show calendar names with events" checked={settings.show_calendar_names} timing={timing} onChange={(show_calendar_names) => onChange({ ...settings, show_calendar_names })} />
      </section>
    </div>
  )
}
