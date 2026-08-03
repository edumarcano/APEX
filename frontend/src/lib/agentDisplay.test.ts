import { describe, expect, it } from 'vitest'

import { agentShortName } from './agentDisplay'

describe('agentShortName', () => {
  it('removes the Apex family prefix for compact Agent surfaces', () => {
    expect(agentShortName('Apex Panthera')).toBe('Panthera')
  })

  it('leaves non-catalog display names unchanged', () => {
    expect(agentShortName('Panthera')).toBe('Panthera')
  })
})
