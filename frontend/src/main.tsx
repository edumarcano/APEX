import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { AtmosphericThemeProvider } from '@/context/AtmosphericThemeContext'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AtmosphericThemeProvider>
      <App />
    </AtmosphericThemeProvider>
  </StrictMode>,
)
