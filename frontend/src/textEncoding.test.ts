import { describe, expect, it } from 'vitest'

const LATIN1_CONTINUATION = '[\\u0080-\\u00bf]'
const WINDOWS_1252_CONTINUATION =
  '[\\u20ac\\u201a\\u0192\\u201e\\u2026\\u2020\\u2021\\u02c6\\u2030\\u0160\\u2039\\u0152\\u017d\\u2018\\u2019\\u201c\\u201d\\u2022\\u2013\\u2014\\u02dc\\u2122\\u0161\\u203a\\u0153\\u017e\\u0178]'
const CONTINUATION = `(?:${LATIN1_CONTINUATION}|${WINDOWS_1252_CONTINUATION})`
const MOJIBAKE = new RegExp(
  `(?:[\\u00c2\\u00c3]${CONTINUATION}|\\u00e2${CONTINUATION}${CONTINUATION})`,
  'u',
)

function containsMojibake(contents: string): boolean {
  return MOJIBAKE.test(contents)
}

const sourceFiles = import.meta.glob('./**/*.{ts,tsx,css}', {
  eager: true,
  query: '?raw',
  import: 'default',
})

describe('frontend source encoding', () => {
  it('detects common malformed UTF-8 sequences in source files', () => {
    const malformed = Object.entries(sourceFiles)
      .filter(([, contents]) => typeof contents === 'string' && containsMojibake(contents))
      .map(([path]) => path)

    expect(malformed).toEqual([])
  })

  it('recognizes representative Latin-1 and Windows-1252 mojibake', () => {
    const malformedExamples = [
      '\u00c3\u00a9',
      '\u00c2\u00a0',
      '\u00c2\u0192',
      '\u00e2\u0080\u0093',
      '\u00e2\u20ac\u201c',
      '\u00e2\u20ac\u2014',
      '\u00e2\u20ac\u2122',
      '\u00e2\u20ac\u0153',
      '\u00e2\u20ac\u201d',
      '\u00e2\u20ac\u00a6',
    ]

    for (const example of malformedExamples) {
      expect(containsMojibake(example)).toBe(true)
    }
  })

  it('allows valid Unicode, including standalone former markers', () => {
    const validExamples = [
      '\u00c2',
      '\u00c3',
      '\u00e2',
      '\u0192',
      'câmera Â Ã â ƒ',
      'c\u00e2mera',
      'caf\u00e9 and ni\u00f1o',
      '\u201cCurly quotes\u201d, an em dash \u2014, and an ellipsis \u2026',
      '\u65e5\u672c\u8a9e and \u{1f680}',
    ]

    for (const example of validExamples) {
      expect(containsMojibake(example)).toBe(false)
    }
  })
})
