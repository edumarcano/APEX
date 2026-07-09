import type { ComponentPropsWithoutRef, ReactElement } from 'react'

export function ClearDayIcon({
  className,
  style,
  ...props
}: ComponentPropsWithoutRef<'svg'>): ReactElement {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
      {...props}
    >
      <style>{`
        @keyframes sun-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes sun-pulse {
          0%, 100% { transform: scale(1); opacity: 0.95; }
          50% { transform: scale(1.08); opacity: 1; }
        }
        .sun-ray-group {
          transform-origin: center;
          animation: sun-spin 25s linear infinite;
        }
        .sun-core {
          transform-origin: center;
          animation: sun-pulse 4s ease-in-out infinite;
        }
      `}</style>
      {/* Glow backing circle */}
      <circle cx="12" cy="12" r="5" className="sun-core" fill="currentColor" fillOpacity="0.05" />
      {/* Main Core */}
      <circle cx="12" cy="12" r="4.5" className="sun-core" fill="currentColor" fillOpacity="0.15" />
      {/* Rays */}
      <g className="sun-ray-group">
        <line x1="12" y1="2" x2="12" y2="4" />
        <line x1="12" y1="20" x2="12" y2="22" />
        <line x1="4.93" y1="4.93" x2="6.34" y2="6.34" />
        <line x1="17.66" y1="17.66" x2="19.07" y2="19.07" />
        <line x1="2" y1="12" x2="4" y2="12" />
        <line x1="20" y1="12" x2="22" y2="12" />
        <line x1="6.34" y1="17.66" x2="4.93" y2="19.07" />
        <line x1="19.07" y1="4.93" x2="17.66" y2="6.34" />
      </g>
    </svg>
  )
}
