import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from 'react'

export type CloudProfile = 'comet' | 'nova' | 'pulsar'

const PROFILE_OPTIONS: ReadonlyArray<{
  key: CloudProfile
  label: string
  subtitle: string
}> = [
  { key: 'comet', label: 'Apex Comet', subtitle: 'Fast' },
  { key: 'nova', label: 'Apex Nova', subtitle: 'Balanced' },
  { key: 'pulsar', label: 'Apex Pulsar', subtitle: 'Advanced' },
]

const PROFILE_LABELS: Record<CloudProfile, string> = {
  comet: 'Apex Comet',
  nova: 'Apex Nova',
  pulsar: 'Apex Pulsar',
}

interface CloudProfileSelectorProps {
  activeProfile: CloudProfile
  onChange: (profile: CloudProfile) => void
  disabled?: boolean
}

export function CloudProfileSelector({
  activeProfile,
  onChange,
  disabled = false,
}: CloudProfileSelectorProps): ReactElement {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const closeDropdown = useCallback((): void => {
    setIsOpen(false)
  }, [])

  const toggleDropdown = useCallback((): void => {
    if (disabled) {
      return
    }
    setIsOpen((prev) => !prev)
  }, [disabled])

  const handleSelect = useCallback(
    (profile: CloudProfile): void => {
      onChange(profile)
      closeDropdown()
    },
    [closeDropdown, onChange],
  )

  const handleTriggerKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeDropdown()
        return
      }

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        toggleDropdown()
      }
    },
    [closeDropdown, toggleDropdown],
  )

  useEffect(() => {
    if (!isOpen) {
      return
    }

    const handlePointerDown = (event: MouseEvent): void => {
      const target = event.target
      if (!(target instanceof Node)) {
        return
      }

      if (!containerRef.current?.contains(target)) {
        closeDropdown()
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
    }
  }, [closeDropdown, isOpen])

  return (
    <div ref={containerRef} className="relative shrink-0">
      <button
        type="button"
        tabIndex={0}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={`Cloud profile: ${PROFILE_LABELS[activeProfile]}`}
        onClick={toggleDropdown}
        onKeyDown={handleTriggerKeyDown}
        className={[
          'flex items-center gap-1 rounded-lg border bg-black/40 px-2.5 py-1.5',
          'font-mono text-[10px] uppercase tracking-wider text-zinc-200',
          'border-white/10 transition-colors',
          'hover:border-[#0F4DB8]/40 focus-visible:outline focus-visible:outline-2',
          'focus-visible:outline-offset-2 focus-visible:outline-[#0F4DB8]',
          disabled ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
        ].join(' ')}
      >
        <span className="whitespace-nowrap">{PROFILE_LABELS[activeProfile]}</span>
        <span className="text-[#0F4DB8]" aria-hidden>
          ▼
        </span>
      </button>

      {isOpen && (
        <ul
          role="listbox"
          aria-label="Select cloud profile"
          className={[
            'absolute bottom-full right-0 z-50 mb-2 min-w-[11rem] overflow-hidden',
            'rounded-lg border border-white/10 bg-zinc-950/95 shadow-2xl backdrop-blur-md',
          ].join(' ')}
        >
          {PROFILE_OPTIONS.map((option) => {
            const isActive = option.key === activeProfile

            return (
              <li key={option.key} role="presentation">
                <button
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  tabIndex={0}
                  onClick={() => {
                    handleSelect(option.key)
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      handleSelect(option.key)
                    }
                    if (event.key === 'Escape') {
                      event.preventDefault()
                      closeDropdown()
                    }
                  }}
                  className={[
                    'flex w-full flex-col items-start px-3 py-2 text-left transition-colors',
                    'hover:bg-[#0F4DB8]/15 focus-visible:bg-[#0F4DB8]/15',
                    'focus-visible:outline-none',
                    isActive ? 'bg-[#0F4DB8]/10' : '',
                  ].join(' ')}
                >
                  <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-100">
                    {option.label}
                  </span>
                  <span className="text-[10px] text-zinc-500">{option.subtitle}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
