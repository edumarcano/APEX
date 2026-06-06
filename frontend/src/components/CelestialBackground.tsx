import { memo, type ReactElement } from 'react'

interface Star {
  id: number
  x: number
  y: number
  radius: number
  animationClass: string
}

function mulberry32(seed: number): () => number {
  let state = seed

  return (): number => {
    state += 0x6d2b79f5
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function buildStars(): Star[] {
  const rng = mulberry32(0x41504558)
  const stars: Star[] = []
  let id = 0

  for (let i = 0; i < 48; i += 1) {
    stars.push({
      id: id++,
      x: Math.floor(rng() * 101),
      y: Math.floor(rng() * 101),
      radius: 0.5 + rng() * 0.3,
      animationClass: 'animate-twinkle-slow',
    })
  }

  for (let i = 0; i < 24; i += 1) {
    stars.push({
      id: id++,
      x: Math.floor(rng() * 101),
      y: Math.floor(rng() * 101),
      radius: 1.0 + rng() * 0.3,
      animationClass: 'animate-twinkle-medium',
    })
  }

  for (let i = 0; i < 8; i += 1) {
    stars.push({
      id: id++,
      x: Math.floor(rng() * 101),
      y: Math.floor(rng() * 101),
      radius: 1.5 + rng() * 0.5,
      animationClass: 'animate-twinkle-fast',
    })
  }

  return stars
}

const STARS = buildStars()

function CelestialBackgroundComponent(): ReactElement {
  return (
    <div
      className="pointer-events-none absolute inset-0 z-[var(--z-celestial-stars)] bg-gradient-to-br from-[#000000] via-[#020617] to-[#050814]"
      aria-hidden="true"
    >
      {STARS.map((star) => (
        <span
          key={star.id}
          className={`absolute rounded-full bg-white ${star.animationClass}`}
          style={{
            left: `${star.x}%`,
            top: `${star.y}%`,
            width: `${star.radius}px`,
            height: `${star.radius}px`,
          }}
        />
      ))}
    </div>
  )
}

export const CelestialBackground = memo(CelestialBackgroundComponent)
