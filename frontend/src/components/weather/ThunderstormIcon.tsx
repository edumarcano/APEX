import type { ComponentPropsWithoutRef, ReactElement } from 'react'

export function ThunderstormIcon({
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
        @keyframes thunder-flash {
          0%, 100% { opacity: 0.1; }
          45% { opacity: 0.1; }
          50% { opacity: 1; transform: scale(1.05); }
          52% { opacity: 0.2; }
          54% { opacity: 1; transform: scale(1.05); }
          58% { opacity: 0.1; }
        }
        @keyframes cloud-rumble {
          0%, 100% { transform: translate(0, 0); }
          49% { transform: translate(0, 0); }
          50% { transform: translate(-0.5px, 0.5px); }
          52% { transform: translate(0.5px, -0.5px); }
          54% { transform: translate(-0.5px, -0.5px); }
          56% { transform: translate(0, 0); }
        }
        .lightning-bolt {
          transform-origin: 13px 14px;
          animation: thunder-flash 4s ease-in-out infinite;
        }
        .thunder-cloud {
          transform-origin: center;
          animation: cloud-rumble 4s ease-in-out infinite;
        }
      `}</style>
      {/* Cloud */}
      <path
        d="M17.5 19A3.5 3.5 0 0 0 21 15.5c0-2.79-2.54-4.5-5-4.5-.42 0-.83.05-1.22.14A6 6 0 0 0 3 11.5c0 3.59 2.91 6.5 6.5 6.5h8Z"
        className="thunder-cloud"
        fill="currentColor"
        fillOpacity="0.15"
      />
      {/* Lightning Bolt */}
      <path
        d="m13 10-3 5h3.5l-3 7 7-9h-4l3-3Z"
        className="lightning-bolt"
        fill="currentColor"
        fillOpacity="0.2"
      />
    </svg>
  )
}
