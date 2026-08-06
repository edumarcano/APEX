import { useState, type ReactElement } from 'react'
import { Plus, X } from 'lucide-react'

import type { FootballTeamSettings } from '../types/settings'

const INPUT_CLASS =
  'hud-command-surface w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 placeholder:text-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-50'

const MAX_FOOTBALL_TEAMS = 3
const MAX_MARKET_SYMBOLS = 8

export function FootballTeamsEditor({
  teams,
  disabled,
  onChange,
}: {
  teams: FootballTeamSettings[]
  disabled?: boolean
  onChange: (next: FootballTeamSettings[]) => void
}): ReactElement {
  const addTeam = (): void => {
    if (teams.length >= MAX_FOOTBALL_TEAMS) {
      return
    }
    onChange([...teams, { id: 0, name: '' }])
  }

  const updateTeam = (index: number, patch: Partial<FootballTeamSettings>): void => {
    onChange(
      teams.map((team, teamIndex) =>
        teamIndex === index ? { ...team, ...patch } : team,
      ),
    )
  }

  const removeTeam = (index: number): void => {
    onChange(teams.filter((_, teamIndex) => teamIndex !== index))
  }

  return (
    <div className="space-y-2 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs tracking-wide text-[color:var(--hud-text)]">Followed teams</p>
        <button
          type="button"
          disabled={disabled || teams.length >= MAX_FOOTBALL_TEAMS}
          onClick={addTeam}
          className="inline-flex items-center gap-1 rounded border border-white/10 px-2 py-0.5 font-mono text-[10px] tracking-wide text-zinc-300 transition-colors hover:border-white/20 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="size-3" aria-hidden />
          Add team
        </button>
      </div>
      <p className="text-[11px] leading-relaxed text-zinc-500">
        Enter football-data.org team IDs and display names (up to three teams).
      </p>
      {teams.length === 0 ? (
        <p className="text-[11px] text-zinc-500">No teams configured.</p>
      ) : (
        <div className="space-y-2">
          {teams.map((team, index) => (
            <div key={`football-team-${index}`} className="grid grid-cols-[5rem_1fr_auto] gap-2">
              <input
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                disabled={disabled}
                value={team.id > 0 ? team.id : ''}
                placeholder="ID"
                aria-label={`Football team ${index + 1} ID`}
                onChange={(event) => {
                  const parsed = Number.parseInt(event.target.value, 10)
                  updateTeam(index, { id: Number.isFinite(parsed) && parsed > 0 ? parsed : 0 })
                }}
                className={INPUT_CLASS}
              />
              <input
                type="text"
                maxLength={100}
                disabled={disabled}
                value={team.name}
                placeholder="Display name"
                aria-label={`Football team ${index + 1} name`}
                onChange={(event) => updateTeam(index, { name: event.target.value })}
                className={INPUT_CLASS}
              />
              <button
                type="button"
                disabled={disabled}
                onClick={() => removeTeam(index)}
                aria-label={`Remove football team ${index + 1}`}
                className="inline-flex items-center justify-center rounded border border-white/10 px-2 text-zinc-400 transition-colors hover:border-white/20 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function MarketSymbolsEditor({
  symbols,
  disabled,
  onChange,
}: {
  symbols: string[]
  disabled?: boolean
  onChange: (next: string[]) => void
}): ReactElement {
  const [draftSymbol, setDraftSymbol] = useState('')

  const addSymbol = (): void => {
    const candidate = draftSymbol.trim().toUpperCase()
    if (!candidate || symbols.length >= MAX_MARKET_SYMBOLS) {
      return
    }
    if (symbols.includes(candidate)) {
      setDraftSymbol('')
      return
    }
    onChange([...symbols, candidate])
    setDraftSymbol('')
  }

  const removeSymbol = (symbol: string): void => {
    onChange(symbols.filter((entry) => entry !== symbol))
  }

  return (
    <div className="space-y-2 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2.5">
      <p className="text-xs tracking-wide text-[color:var(--hud-text)]">Ticker symbols</p>
      <p className="text-[11px] leading-relaxed text-zinc-500">
        Add up to eight symbols for the market monitor. Requires `ALPHA_VANTAGE_API_KEY` in `.env`.
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          disabled={disabled || symbols.length >= MAX_MARKET_SYMBOLS}
          value={draftSymbol}
          placeholder="e.g. SPY"
          aria-label="Market ticker symbol"
          onChange={(event) => setDraftSymbol(event.target.value.toUpperCase())}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              addSymbol()
            }
          }}
          className={INPUT_CLASS}
        />
        <button
          type="button"
          disabled={disabled || symbols.length >= MAX_MARKET_SYMBOLS || !draftSymbol.trim()}
          onClick={addSymbol}
          className="inline-flex shrink-0 items-center gap-1 rounded border border-white/10 px-2.5 py-1 font-mono text-[10px] tracking-wide text-zinc-300 transition-colors hover:border-white/20 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="size-3" aria-hidden />
          Add
        </button>
      </div>
      {symbols.length === 0 ? (
        <p className="text-[11px] text-zinc-500">No symbols configured.</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {symbols.map((symbol) => (
            <span
              key={symbol}
              className="inline-flex items-center gap-1 rounded border border-white/10 bg-zinc-950 px-2 py-0.5 font-mono text-[11px] text-zinc-200"
            >
              {symbol}
              <button
                type="button"
                disabled={disabled}
                onClick={() => removeSymbol(symbol)}
                aria-label={`Remove ${symbol}`}
                className="text-zinc-500 transition-colors hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <X className="size-3" aria-hidden />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
