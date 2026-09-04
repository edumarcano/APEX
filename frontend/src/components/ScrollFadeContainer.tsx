import {
  createElement,
  forwardRef,
  useImperativeHandle,
  type HTMLAttributes,
  type ReactElement,
  type ReactNode,
} from 'react'
import { useScrollFadeMask } from '../hooks/useScrollFadeMask'

export interface ScrollFadeContainerProps extends HTMLAttributes<HTMLElement> {
  as?: 'div' | 'ul' | 'ol'
  children?: ReactNode
}

/**
 * A scrollable container that automatically applies `.list-fade-mask` only
 * when there is additional content below the viewport fold. Once the user scrolls
 * to the actual end (or if the content fits without scrolling), the fade is removed.
 */
export const ScrollFadeContainer = forwardRef<HTMLElement, ScrollFadeContainerProps>(
  function ScrollFadeContainer(
    { as = 'div', className = '', children, ...props },
    forwardedRef,
  ): ReactElement {
    const { elementRef, canScrollDown } = useScrollFadeMask<HTMLElement>()

    useImperativeHandle(forwardedRef, () => elementRef.current as HTMLElement)

    const combinedClassName = [
      className,
      canScrollDown ? 'list-fade-mask' : '',
    ]
      .filter(Boolean)
      .join(' ')

    return createElement(
      as,
      {
        ref: elementRef,
        className: combinedClassName,
        ...props,
      },
      children,
    )
  },
)
