import type { ComponentPropsWithoutRef, ReactElement } from 'react'

export function CloudsIcon({
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
        @keyframes cloud-drift-front {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-0.75px); }
        }
        @keyframes cloud-drift-back {
          0%, 100% { transform: translateX(0); }
          50% { transform: translateX(1px); }
        }
        .cloud-front {
          transform-origin: center;
          animation: cloud-drift-front 5s ease-in-out infinite;
        }
        .cloud-back {
          transform-origin: center;
          animation: cloud-drift-back 8s ease-in-out infinite;
        }
      `}</style>
      {/* Back Cloud (Smaller, transparent fill) */}
      <path
        d="M17.2 16A3 3 0 0 0 20 13c0-2.39-2.18-3.86-4.28-3.86-.36 0-.71.04-1.05.12A5.14 5.14 0 0 0 4.8 9.57c0 3.08 2.5 5.57 5.57 5.57h6.83Z"
        className="cloud-back"
        fill="currentColor"
        fillOpacity="0.05"
        strokeWidth="1.5"
      />
      {/* Front Cloud (Larger, more opaque) */}
      <path
        d="M17.5 19A3.5 3.5 0 0 0 21 15.5c0-2.79-2.54-4.5-5-4.5-.42 0-.83.05-1.22.14A6 6 0 0 0 3 11.5c0 3.59 2.91 6.5 6.5 6.5h8Z"
        className="cloud-front"
        fill="currentColor"
        fillOpacity="0.15"
      />
    </svg>
  )
}
