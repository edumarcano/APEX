import { describe, expect, it } from 'vitest'

const MOJIBAKE = /[\u00c2\u00c3\u00e2\u0192]/
const sourceFiles = import.meta.glob('./**/*.{ts,tsx,css}', {
  eager: true,
  query: '?raw',
  import: 'default',
})

describe('frontend source encoding', () => {
  it('contains no common UTF-8 mojibake markers', () => {
    const malformed = Object.entries(sourceFiles)
      .filter(([, contents]) => typeof contents === 'string' && MOJIBAKE.test(contents))
      .map(([path]) => path)

    expect(malformed).toEqual([])
  })
})
