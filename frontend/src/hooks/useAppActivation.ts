import { useCallback, useState } from 'react'

export type UseAppActivationReturn = {
  activated: boolean
  activate: () => void
  deactivate: () => void
}

export function useAppActivation(): UseAppActivationReturn {
  const [activated, setActivated] = useState(false)

  const activate = useCallback((): void => {
    setActivated(true)
  }, [])

  const deactivate = useCallback((): void => {
    setActivated(false)
  }, [])

  return { activated, activate, deactivate }
}
