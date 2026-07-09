import type { ComponentPropsWithoutRef, ReactElement } from 'react'

export function RainIcon({
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
        @keyframes rain-drop {
          0% {
            stroke-dashoffset: 0;
            opacity: 0;
          }
          30% {
            opacity: 1;
          }
          70% {
            opacity: 1;
          }
          100% {
            stroke-dashoffset: -8;
            opacity: 0;
          }
        }
        .rain-line-1 {
          stroke-dasharray: 4 8;
          animation: rain-drop 2s linear infinite;
        }
        .rain-line-2 {
          stroke-dasharray: 4 8;
          animation: rain-drop 2s linear infinite 0.65s;
        }
        .rain-line-3 {
          stroke-dasharray: 4 8;
          animation: rain-drop 2s linear infinite 1.3s;
        }
        @keyframes cloud-sway {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-0.5px); }
        }
        .rain-cloud {
          transform-origin: center;
          animation: cloud-sway 4s ease-in-out infinite;
        }
      `}</style>
      {/* Cloud backing */}
      <path
        d="M17.5 19A3.5 3.5 0 0 0 21 15.5c0-2.79-2.54-4.5-5-4.5-.42 0-.83.05-1.22.14A6 6 0 0 0 3 11.5c0 3.59 2.91 6.5 6.5 6.5h8Z"
        className="rain-cloud"
        fill="currentColor"
        fillOpacity="0.15"
      />
      {/* Rain Drops */}
      <line x1="9" y1="16" x2="7" y2="20" className="rain-line-1" />
      <line x1="13" y1="16" x2="11" y2="20" className="rain-line-2" />
      <line x1="17" y1="16" x2="15" y2="20" className="rain-line-3" />
    </svg>
  )
}
