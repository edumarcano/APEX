import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ModelMark } from './ModelMark'

describe('ModelMark component', () => {
  it('renders ZAIMono icon for z-ai/glm-5.3-flash even when provider is openrouter', () => {
    const { container } = render(
      <ModelMark modelId="z-ai/glm-5.3-flash" provider="openrouter" size={20} className="custom-mark" />,
    )
    const span = container.querySelector('span')
    expect(span).toBeTruthy()
    expect(span?.className).toContain('custom-mark')
    const svg = span?.querySelector('svg')
    expect(svg).toBeTruthy()
  })

  it('renders ZAIMono icon for model starting with z-ai or containing glm', () => {
    const { container: c1 } = render(<ModelMark modelId="z-ai/something" />)
    expect(c1.querySelector('svg')).toBeTruthy()

    const { container: c2 } = render(<ModelMark modelId="glm-4-flash" />)
    expect(c2.querySelector('svg')).toBeTruthy()
  })

  it('renders ZAIMono icon for openrouter provider', () => {
    const { container } = render(
      <ModelMark modelId="openrouter-generic" provider="openrouter" />,
    )
    const svg = container.querySelector('svg')
    expect(svg).toBeTruthy()
  })

  it('renders DeepSeekColor for deepseek models', () => {
    const { container } = render(
      <ModelMark modelId="deepseek-chat" />,
    )
    const svg = container.querySelector('svg')
    expect(svg).toBeTruthy()
  })

  it('renders fallback Cpu icon for unknown models without provider', () => {
    const { container } = render(<ModelMark modelId="unknown-model" />)
    const svg = container.querySelector('svg')
    expect(svg).toBeTruthy()
  })
})
