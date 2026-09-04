import { describe, expect, it, vi, afterEach } from 'vitest'
import { parseSSEBlock, streamRunEvents } from './cortexStream'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('cortexStream', () => {
  describe('parseSSEBlock', () => {
    it('parses id, event, and JSON data', () => {
      const block = 'id: 42\nevent: response.delta\ndata: {"text":"Hello"}'
      const result = parseSSEBlock(block)
      expect(result).toEqual({
        id: 42,
        event: 'response.delta',
        data: { text: 'Hello' },
      })
    })

    it('identifies heartbeat comment lines', () => {
      const block = ': heartbeat'
      const result = parseSSEBlock(block)
      expect(result).toEqual({ isComment: true })
    })

    it('handles multiline data', () => {
      const block = 'id: 1\nevent: run.snapshot\ndata: {\ndata: "run": {}\ndata: }'
      const result = parseSSEBlock(block)
      expect(result?.id).toBe(1)
      expect(result?.event).toBe('run.snapshot')
      expect(result?.data).toEqual({ run: {} })
    })

    it('strips only a single leading space after data:', () => {
      const block = 'event: response.delta\ndata:   preserve extra leading spaces  '
      const result = parseSSEBlock(block)
      expect(result?.data).toEqual({ raw: '  preserve extra leading spaces  ' })
    })

    it('returns null for empty blocks', () => {
      expect(parseSSEBlock('')).toBeNull()
      expect(parseSSEBlock('   \n\n  ')).toBeNull()
    })
  })

  describe('streamRunEvents', () => {
    function createStreamResponse(chunks: string[]): Response {
      const encoder = new TextEncoder()
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          for (const chunk of chunks) {
            controller.enqueue(encoder.encode(chunk))
          }
          controller.close()
        },
      })
      return new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      })
    }

    it('yields parsed events and stops on run.completed', async () => {
      const runId = '00000000-0000-4000-8000-000000000001'
      const chunks = [
        ': heartbeat\n\nid: 1\nevent: response.delta\ndata: {"text":"Hello"}\n\n',
        'id: 2\nevent: response.delta\ndata: {"text":" World"}\n\n',
        'id: 3\nevent: run.completed\ndata: {"status":"completed"}\n\n',
      ]

      vi.spyOn(globalThis, 'fetch').mockResolvedValue(createStreamResponse(chunks))

      const events = []
      for await (const event of streamRunEvents(runId)) {
        events.push(event)
      }

      expect(events).toHaveLength(3)
      expect(events[0]).toMatchObject({
        sequence: 1,
        run_id: runId,
        type: 'response.delta',
        payload: { text: 'Hello' },
      })
      expect(events[1]).toMatchObject({
        sequence: 2,
        type: 'response.delta',
        payload: { text: ' World' },
      })
      expect(events[2]).toMatchObject({
        sequence: 3,
        type: 'run.completed',
        payload: { status: 'completed' },
      })
    })

    it('reconnects with Last-Event-ID if stream drops before terminal event', async () => {
      const runId = '00000000-0000-4000-8000-000000000002'
      let callCount = 0

      vi.spyOn(globalThis, 'fetch').mockImplementation(async (_url, init) => {
        callCount++
        if (callCount === 1) {
          expect((init?.headers as Record<string, string>)['Last-Event-ID']).toBeUndefined()
          return createStreamResponse(['id: 1\nevent: response.delta\ndata: {"text":"Part 1"}\n\n'])
        }
        expect((init?.headers as Record<string, string>)['Last-Event-ID']).toBe('1')
        return createStreamResponse(['id: 2\nevent: run.completed\ndata: {"status":"completed"}\n\n'])
      })

      const events = []
      for await (const event of streamRunEvents(runId, { maxReconnectAttempts: 2 })) {
        events.push(event)
      }

      expect(events).toHaveLength(2)
      expect(events[0].sequence).toBe(1)
      expect(events[1].sequence).toBe(2)
      expect(callCount).toBe(2)
    })

    it('aborts immediately when signal is cancelled', async () => {
      const runId = '00000000-0000-4000-8000-000000000003'
      const controller = new AbortController()

      vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
        controller.abort()
        return createStreamResponse(['id: 1\nevent: response.delta\ndata: {"text":"Never"}\n\n'])
      })

      const events = []
      for await (const event of streamRunEvents(runId, { signal: controller.signal })) {
        events.push(event)
      }

      expect(events).toHaveLength(0)
    })
  })
})
