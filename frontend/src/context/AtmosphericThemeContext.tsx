import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react'

import { useApexData } from '@/hooks/useApexData'
import type {
  AtmosphericCondition,
  AtmosphericTheme,
  AtmosphericThemeContextType,
} from '@/types/telemetry'

const defaultTheme: AtmosphericTheme = {
  condition: 'neutral',
  isStormy: false,
  bgColors: '#0a0f1d',
  textColor: '#c8d3f5',
  accentColor: '#3b82f6',
}

const AtmosphericThemeContext =
  createContext<AtmosphericThemeContextType | null>(null)

export type AtmosphericThemeProviderProps = {
  children: ReactNode
}

export function AtmosphericThemeProvider({
  children,
}: AtmosphericThemeProviderProps): ReactElement {
  const { data } = useApexData()
  const [theme, setTheme] = useState<AtmosphericTheme>(defaultTheme)

  const updateThemeFromTelemetry = useCallback(
    (weatherReport?: string) => {
      const report = weatherReport ?? data?.weather ?? ''

      let bgColors = '#0a0f1d'
      let textColor = '#c8d3f5'
      let accentColor = '#3b82f6'
      let targetCondition: AtmosphericCondition = 'neutral'

      if (report.includes('Thunderstorm')) {
        bgColors = '#1a202c'
        textColor = '#e2e8f0'
        accentColor = '#06b6d4'
        targetCondition = 'stormy'
      } else if (report.includes('Clear')) {
        bgColors = '#020617'
        textColor = '#f8fafc'
        accentColor = '#eab308'
        targetCondition = 'clear'
      }

      setTheme({
        condition: targetCondition,
        isStormy: targetCondition === 'stormy',
        bgColors,
        textColor,
        accentColor,
      })

      const root = document.documentElement
      root.style.setProperty('--hud-bg', bgColors)
      root.style.setProperty('--hud-text', textColor)
      root.style.setProperty('--hud-accent', accentColor)
    },
    [data?.weather],
  )

  useEffect(() => {
    updateThemeFromTelemetry()
  }, [updateThemeFromTelemetry])

  const value: AtmosphericThemeContextType = { theme, updateThemeFromTelemetry }

  return (
    <AtmosphericThemeContext.Provider value={value}>
      {children}
    </AtmosphericThemeContext.Provider>
  )
}

export function useAtmosphericTheme(): AtmosphericThemeContextType {
  const context = useContext(AtmosphericThemeContext)
  if (context === null) {
    throw new Error(
      'useAtmosphericTheme must be used within an AtmosphericThemeProvider',
    )
  }
  return context
}
