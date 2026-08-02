import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useApexAssistant } from './useApexAssistant'

describe('useApexAssistant', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps Acinonyx requests and visible exchanges single-turn', async () => {
    const queryBodies: Record<string, unknown>[] = []
    let answerNumber = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'POST') {
        queryBodies.push(JSON.parse(String(init.body)) as Record<string, unknown>)
        answerNumber += 1
        return new Response(JSON.stringify({ answer: `answer ${answerNumber}` }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })

    const { result } = renderHook(() => useApexAssistant(false, 'acinonyx'))

    await act(async () => {
      await result.current.queryAssistant('first question', 'acinonyx')
    })
    await act(async () => {
      await result.current.queryAssistant('second question', 'acinonyx')
    })

    expect(queryBodies).toHaveLength(2)
    expect(queryBodies[0].history).toEqual([])
    expect(queryBodies[1].history).toEqual([])
    expect(result.current.assistantHistory).toEqual([
      { role: 'user', content: 'second question' },
      { role: 'model', content: 'answer 2', tool_outputs: [] },
    ])
  })
})
