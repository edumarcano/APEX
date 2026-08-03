import {
  FlaskConical,
  Gem,
  Globe2,
  Orbit,
  ScanSearch,
  ShieldCheck,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import type { ReactElement } from 'react'

import type { AssistantProfile } from '../types/telemetry'

const PROFILE_MARKS: Record<AssistantProfile, { icon: LucideIcon; label: string; className: string }> = {
  acinonyx: { icon: FlaskConical, label: 'Acinonyx profile mark', className: 'border-cyan-300/25 bg-cyan-400/10 text-cyan-200' },
  panthera: { icon: Gem, label: 'Panthera profile mark', className: 'border-purple-300/25 bg-purple-400/10 text-purple-200' },
  neofelis: { icon: Globe2, label: 'Neofelis profile mark', className: 'border-blue-300/25 bg-blue-400/10 text-blue-200' },
  delphinus: { icon: ScanSearch, label: 'Delphinus profile mark', className: 'border-teal-300/25 bg-teal-400/10 text-teal-200' },
  orcinus: { icon: Orbit, label: 'Orcinus profile mark', className: 'border-indigo-300/25 bg-indigo-400/10 text-indigo-200' },
  mus: { icon: ShieldCheck, label: 'Mus profile mark', className: 'border-orange-300/25 bg-orange-400/10 text-orange-200' },
  sorex: { icon: Zap, label: 'Sorex profile mark', className: 'border-amber-300/25 bg-amber-400/10 text-amber-200' },
}

interface ProfileMarkProps {
  profile: AssistantProfile
  size?: 'compact' | 'card'
}

export function ProfileMark({ profile, size = 'compact' }: ProfileMarkProps): ReactElement {
  const mark = PROFILE_MARKS[profile]
  const Icon = mark.icon
  return (
    <span
      aria-label={mark.label}
      className={`inline-flex shrink-0 items-center justify-center rounded-lg border ${mark.className} ${size === 'card' ? 'size-10' : 'size-6'}`}
    >
      <Icon className={size === 'card' ? 'size-5' : 'size-3.5'} aria-hidden />
    </span>
  )
}
