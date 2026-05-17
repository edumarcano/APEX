import type { LucideIcon } from 'lucide-react'
import {
  useId,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from 'react'

export type TelemetryCardProps = {
  title: string
  icon: LucideIcon
  children?: ReactNode
} & Omit<ComponentPropsWithoutRef<'section'>, 'title' | 'children'>

export function TelemetryCard({
  title,
  icon: Icon,
  children,
  className,
  ...sectionProps
}: TelemetryCardProps): ReactElement {
  const headingId = useId()
  const panelClassName = [
    'rounded-2xl border border-[color:var(--hud-border-color)] bg-[color:var(--hud-panel-bg)] p-[var(--hud-panel-pad)]',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <section
      {...sectionProps}
      className={panelClassName}
      aria-labelledby={headingId}
    >
      <header className="mb-4 flex min-h-9 items-center gap-3">
        <Icon
          className="size-5 shrink-0 text-[color:var(--hud-accent)]"
          strokeWidth={1.75}
          aria-hidden
        />
        <h2
          id={headingId}
          className="min-w-0 truncate text-sm font-semibold leading-none tracking-tight text-[color:var(--hud-text)]"
        >
          {title}
        </h2>
      </header>
      <div className="min-w-0">{children}</div>
    </section>
  )
}
