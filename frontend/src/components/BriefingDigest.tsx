import { type ReactElement } from 'react'
import { FileText } from 'lucide-react'
import type { SystemState } from '../types/telemetry'

export interface BriefingDigestProps {
  insights: string[]
  status: SystemState
  isLoading: boolean
  className?: string
}

export function BriefingDigest({ insights, status, isLoading, className }: BriefingDigestProps): ReactElement {
  const labelId = "briefing-digest-title";

  return (
    <section
      className={`relative overflow-hidden rounded-2xl border border-[color:var(--hud-border-color)] hover-blue-subtle p-[var(--hud-panel-pad)] hud-glass transition-all duration-1000 ease-in-out shadow-none min-h-40 flex flex-col justify-start${className ? ` ${className}` : ''}`}
      aria-labelledby={labelId}
    >
      <header className="mb-4 flex min-h-9 items-center gap-3">
        <FileText className="size-5 shrink-0 text-[color:var(--hud-accent)]" strokeWidth={1.75} aria-hidden />
        <h2 id={labelId} className="min-w-0 text-sm font-semibold leading-normal tracking-tight text-[color:var(--hud-text)]">
          Briefing Highlights
        </h2>
      </header>
      
      <div className="min-w-0">
        {isLoading || status === 'idle' ? (
          <div className="space-y-2">
            <div className="h-3 bg-white/5 rounded animate-pulse w-full" />
            <div className="h-3 bg-white/5 rounded animate-pulse w-5/6" />
            <div className="h-3 bg-white/5 rounded animate-pulse w-4/5" />
          </div>
        ) : insights.length === 0 ? (
          <p className="text-sm leading-relaxed text-[color:var(--hud-muted-text)]">No current highlights.</p>
        ) : (
          <ul className="space-y-3 max-h-48 overflow-y-auto pr-1 scrollbar-thin">
            {insights.map((insight, index) => (
              <li key={index} className="flex items-start gap-3 text-sm leading-relaxed text-[color:var(--hud-text)]">
                <span className="text-[#FBBF24] font-bold font-mono select-none shrink-0">{`>`}</span>
                <span className="text-zinc-200">{insight}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
