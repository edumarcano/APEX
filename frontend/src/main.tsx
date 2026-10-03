import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'

import './index.css'
import App from './App.tsx'

const DesktopAdmission = lazy(() => import('./platform/DesktopAdmission.tsx'))

export function ApplicationRoot() {
  // Tauri v2 exposes this marker only in its WebView. Keep browser startup on
  // the existing immediate App path and load all desktop code on demand.
  const isDesktop = '__TAURI_INTERNALS__' in window
  if (!isDesktop) return <App />

  return <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-zinc-300" role="status">Starting APEX…</div>}>
    <DesktopAdmission />
  </Suspense>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ApplicationRoot />
  </StrictMode>,
)
