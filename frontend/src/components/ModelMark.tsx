import GeminiColor from '@lobehub/icons/es/Gemini/components/Color'
import DeepSeekColor from '@lobehub/icons/es/DeepSeek/components/Color'
import GemmaColor from '@lobehub/icons/es/Gemma/components/Color'
import OllamaMono from '@lobehub/icons/es/Ollama/components/Mono'
import OpenAIMono from '@lobehub/icons/es/OpenAI/components/Mono'
import QwenColor from '@lobehub/icons/es/Qwen/components/Color'
import { Cpu } from 'lucide-react'
import type { ReactElement } from 'react'

interface ModelMarkProps {
  modelId?: string | null
  provider?: string | null
  size?: number
  className?: string
}

export function ModelMark({
  modelId,
  provider,
  size = 18,
  className = '',
}: ModelMarkProps): ReactElement {
  const normalizedModel = (modelId ?? '').toLowerCase()
  const normalizedProvider = (provider ?? '').toLowerCase()

  // Gemini family
  if (normalizedModel.startsWith('gemini') || normalizedProvider === 'gemini') {
    return (
      <span className={`inline-flex shrink-0 items-center justify-center ${className}`} aria-hidden>
        <GeminiColor size={size} />
      </span>
    )
  }

  if (normalizedModel.startsWith('deepseek') || normalizedProvider === 'openrouter') {
    return (
      <span className={`inline-flex shrink-0 items-center justify-center ${className}`} aria-hidden>
        <DeepSeekColor size={size} />
      </span>
    )
  }

  // Gemma family
  if (normalizedModel.startsWith('gemma')) {
    return (
      <span className={`inline-flex shrink-0 items-center justify-center ${className}`} aria-hidden>
        <GemmaColor size={size} />
      </span>
    )
  }

  // OpenAI / GPT family
  if (
    normalizedModel.startsWith('gpt') ||
    normalizedModel.startsWith('openai') ||
    normalizedProvider === 'openai'
  ) {
    return (
      <span className={`inline-flex shrink-0 items-center justify-center text-zinc-100 ${className}`} aria-hidden>
        <OpenAIMono size={size} />
      </span>
    )
  }

  // Qwen family
  if (normalizedModel.startsWith('qwen')) {
    return (
      <span className={`inline-flex shrink-0 items-center justify-center ${className}`} aria-hidden>
        <QwenColor size={size} />
      </span>
    )
  }

  // Ollama provider
  if (normalizedProvider === 'ollama') {
    return (
      <span className={`inline-flex shrink-0 items-center justify-center text-zinc-100 ${className}`} aria-hidden>
        <OllamaMono size={size} />
      </span>
    )
  }

  // Fallback for local runtime / other
  return (
    <span className={`inline-flex shrink-0 items-center justify-center text-zinc-400 ${className}`} aria-hidden>
      <Cpu style={{ width: size, height: size }} />
    </span>
  )
}
