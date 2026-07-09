export interface OperationPromptChip {
  label: string
  query: string
}

export const OPERATION_PROMPT_CHIPS: ReadonlyArray<OperationPromptChip> = [
  {
    label: 'Forecast',
    query: 'What is the 5-day weather forecast?',
  },
  {
    label: 'Schedule',
    query: 'Show my calendar events for the next two weeks.',
  },
  {
    label: 'F1 Standings',
    query: 'Who is leading the F1 driver championship?',
  },
  {
    label: 'Reminders',
    query: 'List my pending reminders.',
  },
  {
    label: 'Past Briefings',
    query: 'Compare my last few briefings and summarize changes.',
  },
]
