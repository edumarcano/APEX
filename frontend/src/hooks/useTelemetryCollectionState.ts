import { useCallback, useState } from 'react'

export type UseTelemetryCollectionStateReturn = {
  collectionStarted: boolean
  startCollection: () => void
  resetCollection: () => void
}

export function useTelemetryCollectionState(): UseTelemetryCollectionStateReturn {
  const [collectionStarted, setCollectionStarted] = useState(false)

  const startCollection = useCallback((): void => {
    setCollectionStarted(true)
  }, [])

  const resetCollection = useCallback((): void => {
    setCollectionStarted(false)
  }, [])

  return { collectionStarted, startCollection, resetCollection }
}
