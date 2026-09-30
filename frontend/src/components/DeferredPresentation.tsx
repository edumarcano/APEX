import {
  Component,
  Suspense,
  lazy,
  useState,
  type ComponentType,
  type LazyExoticComponent,
  type ReactNode,
} from 'react'

export type DeferredPresentationProps<P extends object> = {
  load: () => Promise<{ default: ComponentType<P> }>
  componentProps: P
  fallback: ReactNode
  renderError: (retry: () => void) => ReactNode
}

type LazyAttempt<P extends object> = {
  id: number
  Component: LazyExoticComponent<ComponentType<P>>
}

type FailureBoundaryProps = {
  children: ReactNode
  renderError: (retry: () => void) => ReactNode
  retry: () => void
}

type FailureBoundaryState = { failed: boolean }

class FailureBoundary extends Component<FailureBoundaryProps, FailureBoundaryState> {
  state: FailureBoundaryState = { failed: false }

  static getDerivedStateFromError(): FailureBoundaryState {
    return { failed: true }
  }

  render(): ReactNode {
    return this.state.failed ? this.props.renderError(this.props.retry) : this.props.children
  }
}

/** Loads a component on demand and keeps its lazy identity for this boundary mount. */
export function DeferredPresentation<P extends object>({
  load,
  componentProps,
  fallback,
  renderError,
}: DeferredPresentationProps<P>): ReactNode {
  const [attempt, setAttempt] = useState<LazyAttempt<P>>(() => ({ id: 0, Component: lazy(load) }))
  const retry = (): void => setAttempt((current) => ({ id: current.id + 1, Component: lazy(load) }))
  const LoadedComponent = attempt.Component

  return <FailureBoundary key={attempt.id} retry={retry} renderError={renderError}>
    <Suspense fallback={fallback}>
      <LoadedComponent {...componentProps} />
    </Suspense>
  </FailureBoundary>
}
