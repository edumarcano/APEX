import { memo, useEffect, useRef, type ReactElement } from 'react'
import { usePresentationVisibility } from '../hooks/usePresentationVisibility'

export interface CelestialBackgroundProps {
  isLaunch?: boolean
  workspace?: 'overview' | 'briefing' | 'cortex' | 'reports'
  atmosphereGlowColor?: string // RGB string like "15, 77, 184"
}

interface Star {
  id: number
  x: number // Normalized 0..1
  y: number // Normalized 0..1
  radius: number
  tier: 'far' | 'mid' | 'near'
  twinklePhase: number
  twinkleSpeed: number
  baseAlpha: number
  color: [number, number, number]
}

interface BiomeTarget {
  camX: number
  camY: number
  camZoom: number
  primaryColor: [number, number, number]
  secondaryColor: [number, number, number]
  primaryAlpha: number
  secondaryAlpha: number
  centerMaskAlpha: number
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

  // 48 far stars
  for (let i = 0; i < 48; i += 1) {
    stars.push({
      id: id++,
      x: rng(),
      y: rng(),
      radius: 0.5 + rng() * 0.3,
      tier: 'far',
      twinklePhase: rng() * Math.PI * 2,
      twinkleSpeed: 0.6 + rng() * 0.4,
      baseAlpha: 0.4 + rng() * 0.3,
      color: [255, 255, 255],
    })
  }

  // 24 mid stars
  for (let i = 0; i < 24; i += 1) {
    stars.push({
      id: id++,
      x: rng(),
      y: rng(),
      radius: 1.0 + rng() * 0.3,
      tier: 'mid',
      twinklePhase: rng() * Math.PI * 2,
      twinkleSpeed: 1.2 + rng() * 0.6,
      baseAlpha: 0.6 + rng() * 0.25,
      color: rng() > 0.4 ? [255, 255, 255] : [200, 225, 255],
    })
  }

  // 8 near stars
  for (let i = 0; i < 8; i += 1) {
    stars.push({
      id: id++,
      x: rng(),
      y: rng(),
      radius: 1.5 + rng() * 0.5,
      tier: 'near',
      twinklePhase: rng() * Math.PI * 2,
      twinkleSpeed: 1.8 + rng() * 1.0,
      baseAlpha: 0.85 + rng() * 0.15,
      color: rng() > 0.5 ? [255, 255, 255] : [220, 235, 255],
    })
  }

  return stars
}

const STARS = buildStars()

function parseRgb(colorStr?: string): [number, number, number] {
  if (!colorStr) return [15, 77, 184]
  const parts = colorStr.split(',').map((p) => Number.parseInt(p.trim(), 10))
  if (parts.length >= 3 && !parts.some(Number.isNaN)) {
    return [parts[0], parts[1], parts[2]]
  }
  return [15, 77, 184]
}

function getBiomeTarget(
  isLaunch?: boolean,
  workspace?: 'overview' | 'briefing' | 'cortex' | 'reports',
): BiomeTarget {
  if (isLaunch) {
    return {
      camX: 0,
      camY: 0,
      camZoom: 1.1,
      primaryColor: [8, 47, 122], // Deep Cerulean
      secondaryColor: [217, 119, 6], // Gold/Bronze stellar dust
      primaryAlpha: 0.32,
      secondaryAlpha: 0.18,
      centerMaskAlpha: 0.25,
    }
  }

  switch (workspace) {
    case 'briefing':
      return {
        camX: -0.12,
        camY: 0.04,
        camZoom: 1.0,
        primaryColor: [251, 191, 36], // Solar Corona / Amber Horizon
        secondaryColor: [217, 119, 6],
        primaryAlpha: 0.26,
        secondaryAlpha: 0.14,
        centerMaskAlpha: 0.50,
      }
    case 'cortex':
      return {
        camX: 0.08,
        camY: -0.10,
        camZoom: 1.0,
        primaryColor: [126, 34, 206], // Zenith Violet Ion Cloud
        secondaryColor: [88, 28, 135],
        primaryAlpha: 0.28,
        secondaryAlpha: 0.15,
        centerMaskAlpha: 0.85,
      }
    case 'reports':
      return {
        camX: 0.14,
        camY: 0.04,
        camZoom: 1.0,
        primaryColor: [148, 163, 184], // Platinum Starlight Void
        secondaryColor: [203, 213, 225],
        primaryAlpha: 0.14,
        secondaryAlpha: 0.08,
        centerMaskAlpha: 0.90,
      }
    case 'overview':
    default:
      return {
        camX: 0,
        camY: 0.08,
        camZoom: 1.0,
        primaryColor: [15, 77, 184], // Nadir Void Blue
        secondaryColor: [8, 47, 122],
        primaryAlpha: 0.30,
        secondaryAlpha: 0.12,
        centerMaskAlpha: 0.50,
      }
  }
}

function lerp(current: number, target: number, rate: number): number {
  return current + (target - current) * rate
}

function lerpColor(
  current: [number, number, number],
  target: [number, number, number],
  rate: number,
): [number, number, number] {
  return [
    lerp(current[0], target[0], rate),
    lerp(current[1], target[1], rate),
    lerp(current[2], target[2], rate),
  ]
}

function wrap(val: number, max: number, margin: number): number {
  const range = max + margin * 2
  return ((((val + margin) % range) + range) % range) - margin
}

function CelestialBackgroundComponent({
  isLaunch = false,
  workspace = 'overview',
  atmosphereGlowColor,
}: CelestialBackgroundProps): ReactElement {
  const presentationVisible = usePresentationVisibility()
  const presentationVisibleRef = useRef(presentationVisible)
  const presentationChangeHandlerRef = useRef<(() => void) | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    presentationVisibleRef.current = presentationVisible
    presentationChangeHandlerRef.current?.()
  }, [presentationVisible])

  // Track props in refs for animation loop
  const propsRef = useRef({ isLaunch, workspace, atmosphereGlowColor })

  useEffect(() => {
    propsRef.current = { isLaunch, workspace, atmosphereGlowColor }
  }, [isLaunch, workspace, atmosphereGlowColor])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    let animationFrameId: number | null = null
    let targetMouseX = 0
    let targetMouseY = 0
    let currentMouseX = 0
    let currentMouseY = 0

    // Initial state based on target
    const initialTarget = getBiomeTarget(propsRef.current.isLaunch, propsRef.current.workspace)
    let currentCamX = initialTarget.camX
    let currentCamY = initialTarget.camY
    let currentCamZoom = initialTarget.camZoom
    let currentPrimaryColor: [number, number, number] = [...initialTarget.primaryColor]
    let currentSecondaryColor: [number, number, number] = [...initialTarget.secondaryColor]
    let currentPrimaryAlpha = initialTarget.primaryAlpha
    let currentSecondaryAlpha = initialTarget.secondaryAlpha
    let currentCenterMaskAlpha = initialTarget.centerMaskAlpha
    let currentReactiveColor: [number, number, number] = parseRgb(propsRef.current.atmosphereGlowColor)

    // Motion preference query
    const motionQuery = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)')
      : null
    let prefersReducedMotion = motionQuery ? motionQuery.matches : false

    let cssWidth = 0
    let cssHeight = 0

    const resizeCanvas = (): void => {
      const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
      const rect = canvas.getBoundingClientRect()
      cssWidth = Math.max(1, Math.floor(rect.width || (typeof window !== 'undefined' ? window.innerWidth : 800)))
      cssHeight = Math.max(1, Math.floor(rect.height || (typeof window !== 'undefined' ? window.innerHeight : 600)))
      canvas.width = Math.floor(cssWidth * dpr)
      canvas.height = Math.floor(cssHeight * dpr)
    }

    resizeCanvas()

    const drawFrame = (timestampSeconds: number, isStatic = false): void => {
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
      ctx.save()
      ctx.scale(dpr, dpr)

      const target = getBiomeTarget(propsRef.current.isLaunch, propsRef.current.workspace)
      const targetReactive = parseRgb(propsRef.current.atmosphereGlowColor)

      if (isStatic) {
        currentCamX = target.camX
        currentCamY = target.camY
        currentCamZoom = target.camZoom
        currentPrimaryColor = [...target.primaryColor]
        currentSecondaryColor = [...target.secondaryColor]
        currentPrimaryAlpha = target.primaryAlpha
        currentSecondaryAlpha = target.secondaryAlpha
        currentCenterMaskAlpha = target.centerMaskAlpha
        currentReactiveColor = [...targetReactive]
        currentMouseX = 0
        currentMouseY = 0
      } else {
        const lerpRate = 0.05
        currentCamX = lerp(currentCamX, target.camX, lerpRate)
        currentCamY = lerp(currentCamY, target.camY, lerpRate)
        currentCamZoom = lerp(currentCamZoom, target.camZoom, lerpRate)
        currentPrimaryColor = lerpColor(currentPrimaryColor, target.primaryColor, lerpRate)
        currentSecondaryColor = lerpColor(currentSecondaryColor, target.secondaryColor, lerpRate)
        currentPrimaryAlpha = lerp(currentPrimaryAlpha, target.primaryAlpha, lerpRate)
        currentSecondaryAlpha = lerp(currentSecondaryAlpha, target.secondaryAlpha, lerpRate)
        currentCenterMaskAlpha = lerp(currentCenterMaskAlpha, target.centerMaskAlpha, lerpRate)
        currentReactiveColor = lerpColor(currentReactiveColor, targetReactive, lerpRate)
        currentMouseX = lerp(currentMouseX, targetMouseX, lerpRate)
        currentMouseY = lerp(currentMouseY, targetMouseY, lerpRate)
      }

      const w = cssWidth
      const h = cssHeight
      const cx = w * 0.5
      const cy = h * 0.5

      // Layer 1: Deep Space Void Base
      const bgGrad = ctx.createLinearGradient(0, 0, w, h)
      bgGrad.addColorStop(0, '#000000')
      bgGrad.addColorStop(0.5, '#020617')
      bgGrad.addColorStop(1, '#050814')
      ctx.fillStyle = bgGrad
      ctx.fillRect(0, 0, w, h)

      // Layer 2: Deterministic Starfield
      const panX = currentCamX * w
      const panY = currentCamY * h

      for (let i = 0; i < STARS.length; i += 1) {
        const star = STARS[i]
        const tierMultiplier = star.tier === 'far' ? 12 : star.tier === 'mid' ? 28 : 48
        const parallaxX = currentMouseX * tierMultiplier
        const parallaxY = currentMouseY * tierMultiplier

        const rawX = (star.x * w) - panX
        const rawY = (star.y * h) - panY

        const zoomedX = cx + (rawX - cx) * currentCamZoom + parallaxX
        const zoomedY = cy + (rawY - cy) * currentCamZoom + parallaxY

        const x = wrap(zoomedX, w, 40)
        const y = wrap(zoomedY, h, 40)

        const scintillation = isStatic
          ? 0.8
          : 0.65 + 0.35 * Math.sin(timestampSeconds * star.twinkleSpeed + star.twinklePhase)
        const alpha = Math.min(1, Math.max(0, star.baseAlpha * scintillation))
        const starRadius = star.radius * currentCamZoom

        if (star.tier === 'near') {
          // Near star lens flare and halo
          const glowRadius = starRadius * 3.5
          const halo = ctx.createRadialGradient(x, y, 0, x, y, glowRadius)
          halo.addColorStop(0, `rgba(${star.color.join(',')}, ${(alpha * 0.85).toFixed(3)})`)
          halo.addColorStop(0.4, `rgba(${star.color.join(',')}, ${(alpha * 0.25).toFixed(3)})`)
          halo.addColorStop(1, `rgba(${star.color.join(',')}, 0)`)
          ctx.fillStyle = halo
          ctx.beginPath()
          ctx.arc(x, y, glowRadius, 0, Math.PI * 2)
          ctx.fill()

          // Core
          ctx.fillStyle = `rgba(255, 255, 255, ${alpha.toFixed(3)})`
          ctx.beginPath()
          ctx.arc(x, y, starRadius, 0, Math.PI * 2)
          ctx.fill()

          // 4-point subtle diffraction spike
          if (!isStatic && scintillation > 0.82) {
            const spikeLen = starRadius * 3.5
            ctx.strokeStyle = `rgba(255, 255, 255, ${(alpha * 0.35).toFixed(3)})`
            ctx.lineWidth = 0.75
            ctx.beginPath()
            ctx.moveTo(x - spikeLen, y)
            ctx.lineTo(x + spikeLen, y)
            ctx.moveTo(x, y - spikeLen)
            ctx.lineTo(x, y + spikeLen)
            ctx.stroke()
          }
        } else {
          ctx.fillStyle = `rgba(${star.color.join(',')}, ${alpha.toFixed(3)})`
          ctx.beginPath()
          ctx.arc(x, y, starRadius, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // Layer 3 & 4: Volumetric Interstellar Gas (Workspace Biomes)
      const maxDim = Math.max(w, h)
      const t = timestampSeconds

      // Cloud 1: Primary Biome
      const c1DriftX = isStatic ? 0 : Math.sin(t * 0.25) * w * 0.06
      const c1DriftY = isStatic ? 0 : Math.cos(t * 0.3) * h * 0.05
      const c1x = w * 0.45 - currentCamX * w * 0.4 + c1DriftX
      const c1y = h * 0.45 - currentCamY * h * 0.4 + c1DriftY
      const c1r = maxDim * 0.65 * currentCamZoom

      const c1Grad = ctx.createRadialGradient(c1x, c1y, 0, c1x, c1y, c1r)
      const pRgb = currentPrimaryColor.map((v) => Math.round(v)).join(',')
      c1Grad.addColorStop(0, `rgba(${pRgb}, ${currentPrimaryAlpha.toFixed(3)})`)
      c1Grad.addColorStop(0.5, `rgba(${pRgb}, ${(currentPrimaryAlpha * 0.35).toFixed(3)})`)
      c1Grad.addColorStop(1, `rgba(${pRgb}, 0)`)
      ctx.fillStyle = c1Grad
      ctx.fillRect(0, 0, w, h)

      // Cloud 2: Secondary Biome
      const c2DriftX = isStatic ? 0 : Math.cos(t * 0.22) * w * 0.06
      const c2DriftY = isStatic ? 0 : Math.sin(t * 0.28) * h * 0.05
      const c2x = w * 0.55 - currentCamX * w * 0.4 + c2DriftX
      const c2y = h * 0.55 - currentCamY * h * 0.4 + c2DriftY
      const c2r = maxDim * 0.55 * currentCamZoom

      const c2Grad = ctx.createRadialGradient(c2x, c2y, 0, c2x, c2y, c2r)
      const sRgb = currentSecondaryColor.map((v) => Math.round(v)).join(',')
      c2Grad.addColorStop(0, `rgba(${sRgb}, ${currentSecondaryAlpha.toFixed(3)})`)
      c2Grad.addColorStop(0.45, `rgba(${sRgb}, ${(currentSecondaryAlpha * 0.3).toFixed(3)})`)
      c2Grad.addColorStop(1, `rgba(${sRgb}, 0)`)
      ctx.fillStyle = c2Grad
      ctx.fillRect(0, 0, w, h)

      // Layer 5: Dual-Layer Reactive Illumination (Central Volumetric Pulse)
      const flarePulse = isStatic ? 1.0 : 0.92 + 0.08 * Math.sin(t * 1.5)
      const fx = cx - currentCamX * w * 0.25
      const fy = cy - currentCamY * h * 0.25
      const fr = maxDim * 0.48 * flarePulse

      const flareGrad = ctx.createRadialGradient(fx, fy, 0, fx, fy, fr)
      const rRgb = currentReactiveColor.map((v) => Math.round(v)).join(',')
      flareGrad.addColorStop(0, `rgba(${rRgb}, 0.24)`)
      flareGrad.addColorStop(0.45, `rgba(${rRgb}, 0.07)`)
      flareGrad.addColorStop(0.85, `rgba(${rRgb}, 0)`)
      ctx.fillStyle = flareGrad
      ctx.fillRect(0, 0, w, h)

      // Layer 6: Density-Adaptive Center Masking & Edge Vignette
      const vignetteRadius = Math.sqrt(cx * cx + cy * cy)
      const vignetteGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, vignetteRadius)
      vignetteGrad.addColorStop(0, `rgba(0, 0, 0, ${currentCenterMaskAlpha.toFixed(3)})`)
      vignetteGrad.addColorStop(0.45, `rgba(0, 0, 0, ${(currentCenterMaskAlpha * 0.65).toFixed(3)})`)
      vignetteGrad.addColorStop(0.8, 'rgba(0, 0, 0, 0.45)')
      vignetteGrad.addColorStop(1, 'rgba(0, 0, 0, 0.90)')
      ctx.fillStyle = vignetteGrad
      ctx.fillRect(0, 0, w, h)

      ctx.restore()
    }

    const renderLoop = (timeMs: number): void => {
      drawFrame(timeMs * 0.001, false)
      animationFrameId = requestAnimationFrame(renderLoop)
    }

    const startLoop = (): void => {
      if (prefersReducedMotion) {
        drawFrame(0, true)
        return
      }
      if (animationFrameId === null && presentationVisibleRef.current && (!document || !document.hidden)) {
        animationFrameId = requestAnimationFrame(renderLoop)
      }
    }

    const stopLoop = (): void => {
      if (animationFrameId !== null) {
        cancelAnimationFrame(animationFrameId)
        animationFrameId = null
      }
    }

    const handleResize = (): void => {
      resizeCanvas()
      if (prefersReducedMotion) {
        drawFrame(0, true)
      }
    }

    const handleMouseMove = (e: MouseEvent): void => {
      if (prefersReducedMotion || typeof window === 'undefined') return
      targetMouseX = (e.clientX / (window.innerWidth || 1)) - 0.5
      targetMouseY = (e.clientY / (window.innerHeight || 1)) - 0.5
    }

    const handleVisibilityChange = (): void => {
      if (typeof document === 'undefined') return
      if (document.hidden || !presentationVisibleRef.current) {
        stopLoop()
      } else {
        startLoop()
      }
    }

    const handleMotionChange = (e: MediaQueryListEvent): void => {
      prefersReducedMotion = e.matches
      if (prefersReducedMotion) {
        stopLoop()
        drawFrame(0, true)
      } else {
        startLoop()
      }
    }

    if (typeof window !== 'undefined') {
      window.addEventListener('resize', handleResize)
      window.addEventListener('mousemove', handleMouseMove, { passive: true })
    }
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', handleVisibilityChange)
    }
    if (motionQuery) {
      if (typeof motionQuery.addEventListener === 'function') {
        motionQuery.addEventListener('change', handleMotionChange)
      } else if (typeof motionQuery.addListener === 'function') {
        // Fallback for older environments
        motionQuery.addListener(handleMotionChange)
      }
    }

    presentationChangeHandlerRef.current = handleVisibilityChange

    startLoop()

    return () => {
      stopLoop()
      if (typeof window !== 'undefined') {
        window.removeEventListener('resize', handleResize)
        window.removeEventListener('mousemove', handleMouseMove)
      }
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange)
      }
      if (motionQuery) {
        if (typeof motionQuery.removeEventListener === 'function') {
          motionQuery.removeEventListener('change', handleMotionChange)
        } else if (typeof motionQuery.removeListener === 'function') {
          motionQuery.removeListener(handleMotionChange)
        }
      }
      presentationChangeHandlerRef.current = null
    }
  }, [])

  // If props change in reduced-motion mode, trigger an immediate re-render
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const motionQuery = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)')
      : null
    if (motionQuery?.matches) {
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      const target = getBiomeTarget(isLaunch, workspace)
      const targetReactive = parseRgb(atmosphereGlowColor)
      const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
      const rect = canvas.getBoundingClientRect()
      const w = Math.max(1, Math.floor(rect.width || (typeof window !== 'undefined' ? window.innerWidth : 800)))
      const h = Math.max(1, Math.floor(rect.height || (typeof window !== 'undefined' ? window.innerHeight : 600)))

      ctx.save()
      ctx.scale(dpr, dpr)

      const bgGrad = ctx.createLinearGradient(0, 0, w, h)
      bgGrad.addColorStop(0, '#000000')
      bgGrad.addColorStop(0.5, '#020617')
      bgGrad.addColorStop(1, '#050814')
      ctx.fillStyle = bgGrad
      ctx.fillRect(0, 0, w, h)

      const cx = w * 0.5
      const cy = h * 0.5
      const panX = target.camX * w
      const panY = target.camY * h

      for (let i = 0; i < STARS.length; i += 1) {
        const star = STARS[i]
        const rawX = (star.x * w) - panX
        const rawY = (star.y * h) - panY
        const zoomedX = cx + (rawX - cx) * target.camZoom
        const zoomedY = cy + (rawY - cy) * target.camZoom
        const x = wrap(zoomedX, w, 40)
        const y = wrap(zoomedY, h, 40)
        const alpha = Math.min(1, Math.max(0, star.baseAlpha * 0.8))
        const starRadius = star.radius * target.camZoom

        ctx.fillStyle = `rgba(${star.color.join(',')}, ${alpha.toFixed(3)})`
        ctx.beginPath()
        ctx.arc(x, y, starRadius, 0, Math.PI * 2)
        ctx.fill()
      }

      const maxDim = Math.max(w, h)
      const c1x = w * 0.45 - target.camX * w * 0.4
      const c1y = h * 0.45 - target.camY * h * 0.4
      const c1r = maxDim * 0.65 * target.camZoom
      const c1Grad = ctx.createRadialGradient(c1x, c1y, 0, c1x, c1y, c1r)
      const pRgb = target.primaryColor.join(',')
      c1Grad.addColorStop(0, `rgba(${pRgb}, ${target.primaryAlpha.toFixed(3)})`)
      c1Grad.addColorStop(0.5, `rgba(${pRgb}, ${(target.primaryAlpha * 0.35).toFixed(3)})`)
      c1Grad.addColorStop(1, `rgba(${pRgb}, 0)`)
      ctx.fillStyle = c1Grad
      ctx.fillRect(0, 0, w, h)

      const fx = cx - target.camX * w * 0.25
      const fy = cy - target.camY * h * 0.25
      const fr = maxDim * 0.48
      const flareGrad = ctx.createRadialGradient(fx, fy, 0, fx, fy, fr)
      const rRgb = targetReactive.join(',')
      flareGrad.addColorStop(0, `rgba(${rRgb}, 0.24)`)
      flareGrad.addColorStop(0.45, `rgba(${rRgb}, 0.07)`)
      flareGrad.addColorStop(0.85, `rgba(${rRgb}, 0)`)
      ctx.fillStyle = flareGrad
      ctx.fillRect(0, 0, w, h)

      const vignetteRadius = Math.sqrt(cx * cx + cy * cy)
      const vignetteGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, vignetteRadius)
      vignetteGrad.addColorStop(0, `rgba(0, 0, 0, ${target.centerMaskAlpha.toFixed(3)})`)
      vignetteGrad.addColorStop(0.45, `rgba(0, 0, 0, ${(target.centerMaskAlpha * 0.65).toFixed(3)})`)
      vignetteGrad.addColorStop(0.8, 'rgba(0, 0, 0, 0.45)')
      vignetteGrad.addColorStop(1, 'rgba(0, 0, 0, 0.90)')
      ctx.fillStyle = vignetteGrad
      ctx.fillRect(0, 0, w, h)

      ctx.restore()
    }
  }, [isLaunch, workspace, atmosphereGlowColor])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-[var(--z-celestial-stars)] h-full w-full"
    />
  )
}

export const CelestialBackground = memo(CelestialBackgroundComponent)
