import type { ReactElement } from 'react'

import type { SettingsEffectiveTiming } from '../types/settings'

export type SettingsStatusTone = 'neutral' | 'ok' | 'warn' | 'error'

function TimingChip({ label }: { label: SettingsEffectiveTiming }): ReactElement {
  const muted = label === 'Active'
  return (
    <span
      className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] tracking-[0.08em] uppercase ${
        muted
          ? 'border-white/10 text-zinc-500'
          : 'border-amber-400/30 text-amber-200/90'
      }`}
    >
      {label}
    </span>
  )
}

export function SettingsToggle({
  id,
  label,
  checked,
  disabled,
  timing,
  onChange,
}: {
  id: string
  label: string
  checked: boolean
  disabled?: boolean
  timing: SettingsEffectiveTiming
  onChange: (next: boolean) => void
}): ReactElement {
  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 ${
        disabled ? 'opacity-50' : ''
      }`}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <label
          htmlFor={id}
          className={`text-xs tracking-wide text-[color:var(--hud-text)] ${
            disabled ? 'cursor-not-allowed' : 'cursor-pointer'
          }`}
        >
          {label}
        </label>
        <TimingChip label={timing} />
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed ${
          checked
            ? 'border-emerald-400/40 bg-emerald-500/30'
            : 'border-white/15 bg-white/5'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 size-4 rounded-full bg-white/90 transition-transform motion-reduce:transition-none ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}

export function SettingsSelect<T extends string>({
  id,
  label,
  value,
  options,
  timing,
  disabled,
  onChange,
}: {
  id: string
  label: string
  value: T
  options: readonly { value: T; label: string }[]
  timing: SettingsEffectiveTiming
  disabled?: boolean
  onChange: (next: T) => void
}): ReactElement {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <label
          htmlFor={id}
          className="text-xs tracking-wide text-[color:var(--hud-text)]"
        >
          {label}
        </label>
        <TimingChip label={timing} />
      </div>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as T)}
        className="hud-command-surface w-full rounded-md border border-white/10 bg-zinc-950 px-2.5 py-1.5 font-mono text-xs text-zinc-100 [color-scheme:dark] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--hud-accent)] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} className="bg-zinc-950 text-zinc-100">
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}

export function SectionHeading({
  id,
  title,
}: {
  id: string
  title: string
}): ReactElement {
  return (
    <h3
      id={id}
      className="font-orbitron text-[10px] font-semibold tracking-[0.16em] text-zinc-400 uppercase"
    >
      {title}
    </h3>
  )
}

export function StatusRow({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: SettingsStatusTone
}): ReactElement {
  const valueClass =
    tone === 'ok'
      ? 'text-emerald-300/90'
      : tone === 'warn'
        ? 'text-amber-200/90'
        : tone === 'error'
          ? 'text-red-300/90'
          : 'text-[color:var(--hud-muted-text)]'

  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/5 py-1.5 last:border-b-0">
      <span className="text-[11px] text-zinc-400">{label}</span>
      <span className={`max-w-[60%] text-right font-mono text-[11px] ${valueClass}`}>
        {value}
      </span>
    </div>
  )
}
