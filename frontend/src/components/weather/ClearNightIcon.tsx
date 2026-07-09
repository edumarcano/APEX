import type { ComponentPropsWithoutRef, ReactElement } from 'react'

export function ClearNightIcon({
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
        @keyframes moon-float {
          0%, 100% { transform: translateY(0) rotate(0deg); }
          50% { transform: translateY(-1px) rotate(-2deg); }
        }
        @keyframes star-twinkle {
          0%, 100% { opacity: 0.3; transform: scale(0.8); }
          50% { opacity: 1; transform: scale(1.1); }
        }
        .moon-body {
          transform-origin: center;
          animation: moon-float 6s ease-in-out infinite;
        }
        .twinkle-star-1 {
          transform-origin: 19px 5px;
          animation: star-twinkle 2s ease-in-out infinite;
        }
        .twinkle-star-2 {
          transform-origin: 15px 12px;
          animation: star-twinkle 3s ease-in-out infinite 0.75s;
        }
      `}</style>
      {/* Background soft glow */}
      <path
        d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"
        className="moon-body"
        fill="currentColor"
        fillOpacity="0.1"
      />
      {/* Moon path */}
      <path
        d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"
        className="moon-body"
      />
      {/* Star 1 */}
      <path
        d="M19 3v4M17 5h4"
        strokeWidth="1"
        className="twinkle-star-1"
      />
      {/* Star 2 (small) */}
      <path
        d="M15 11v2M14 12h2"
        strokeWidth="0.75"
        className="twinkle-star-2"
      />
    </svg>
  )
}
