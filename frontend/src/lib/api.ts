export const API_BASE = 'http://127.0.0.1:8000'

export const API_ENDPOINTS = {
  cortexLocalModelLoad: `${API_BASE}/api/v1/cortex/local-model/load`,
  cortexLocalModelUnload: `${API_BASE}/api/v1/cortex/local-model/unload`,
  cortexToolCatalog: (modelId?: string) =>
    modelId
      ? `${API_BASE}/api/v1/cortex/tool-catalog?model_id=${encodeURIComponent(modelId)}`
      : `${API_BASE}/api/v1/cortex/tool-catalog`,
  cortexToolPreflight: `${API_BASE}/api/v1/cortex/tool-preflight`,
  cortexToolProfiles: `${API_BASE}/api/v1/cortex/tool-profiles`,
  cortexToolProfile: (profileId: string) =>
    `${API_BASE}/api/v1/cortex/tool-profiles/${encodeURIComponent(profileId)}`,
  cortexToolProfileDefault: `${API_BASE}/api/v1/cortex/tool-profiles/default`,
  cortexAgent: `${API_BASE}/api/v1/cortex/agent`,
  cortexModelVerify: `${API_BASE}/api/v1/cortex/models/verify`,
  cortexConversations: `${API_BASE}/api/v1/cortex/conversations`,
  cortexConversation: (conversationId: string) => `${API_BASE}/api/v1/cortex/conversations/${encodeURIComponent(conversationId)}`,
  cortexConversationTurns: (conversationId: string) => `${API_BASE}/api/v1/cortex/conversations/${encodeURIComponent(conversationId)}/turns`,
  cortexConversationRuns: (conversationId: string) => `${API_BASE}/api/v1/cortex/conversations/${encodeURIComponent(conversationId)}/runs`,
  cortexRuns: (params?: { status?: string; limit?: number }) => {
    const query = new URLSearchParams()
    if (params?.status) query.set('status', params.status)
    if (params?.limit) query.set('limit', String(params.limit))
    const qs = query.toString()
    return qs ? `${API_BASE}/api/v1/cortex/runs?${qs}` : `${API_BASE}/api/v1/cortex/runs`
  },
  cortexRun: (runId: string) => `${API_BASE}/api/v1/cortex/runs/${encodeURIComponent(runId)}`,
  cortexRunCancel: (runId: string) => `${API_BASE}/api/v1/cortex/runs/${encodeURIComponent(runId)}/cancel`,
  cortexRunEvents: (runId: string) => `${API_BASE}/api/v1/cortex/runs/${encodeURIComponent(runId)}/events`,
  cortexContext: `${API_BASE}/api/v1/cortex/context`,
  cortexContextRecord: (recordId: string) => `${API_BASE}/api/v1/cortex/context/${encodeURIComponent(recordId)}`,
  cortexContextSensitivity: (recordId: string) => `${API_BASE}/api/v1/cortex/context/${encodeURIComponent(recordId)}/sensitivity`,
  cortexContextEntities: `${API_BASE}/api/v1/cortex/context/entities`,
  cortexContextCapture: `${API_BASE}/api/v1/cortex/context/captures`,
  cortexContextSave: `${API_BASE}/api/v1/cortex/context/saves`,
  cortexContextReviews: `${API_BASE}/api/v1/cortex/context/reviews`,
  cortexContextReview: (reviewId: string) => `${API_BASE}/api/v1/cortex/context/reviews/${encodeURIComponent(reviewId)}`,
  cortexContextReviewDecision: (reviewId: string, decision: 'accept' | 'reject' | 'refresh') => `${API_BASE}/api/v1/cortex/context/reviews/${encodeURIComponent(reviewId)}/${decision}`,
  cortexVault: `${API_BASE}/api/v1/cortex/vault`,
  cortexVaultPreview: `${API_BASE}/api/v1/cortex/vault/preview`,
  cortexVaultRefresh: `${API_BASE}/api/v1/cortex/vault/refresh`,
  cortexVaultCopies: `${API_BASE}/api/v1/cortex/vault/copies`,
  activityReports: (params?: { clientId?: string; disposition?: string; limit?: number }) => {
    const query = new URLSearchParams()
    if (params?.clientId) query.set('client_id', params.clientId)
    if (params?.disposition) query.set('disposition', params.disposition)
    if (params?.limit) query.set('limit', String(params.limit))
    const qs = query.toString()
    return qs ? `${API_BASE}/api/v1/activity/reports?${qs}` : `${API_BASE}/api/v1/activity/reports`
  },
  activityReport: (reportId: string) => `${API_BASE}/api/v1/activity/reports/${encodeURIComponent(reportId)}`,
  activityReportContextReviews: (reportId: string) => `${API_BASE}/api/v1/activity/reports/${encodeURIComponent(reportId)}/context-reviews`,
  activityReportContextProposals: (reportId: string) => `${API_BASE}/api/v1/activity/reports/${encodeURIComponent(reportId)}/context-proposals`,
  activityMailboxStatus: `${API_BASE}/api/v1/activity/mailbox/status`,
  activityMailboxScan: `${API_BASE}/api/v1/activity/mailbox/scan`,
  cortexContextActions: `${API_BASE}/api/v1/cortex/context/actions`,
  cortexRetrievalStatus: `${API_BASE}/api/v1/cortex/retrieval/status`,
  cortexRetrievalPrepare: `${API_BASE}/api/v1/cortex/retrieval/prepare`,
  actions: `${API_BASE}/api/v1/actions`,
  action: (actionId: string) => `${API_BASE}/api/v1/actions/${encodeURIComponent(actionId)}`,
  actionApprove: (actionId: string) => `${API_BASE}/api/v1/actions/${encodeURIComponent(actionId)}/approve`,
  actionReject: (actionId: string) => `${API_BASE}/api/v1/actions/${encodeURIComponent(actionId)}/reject`,
  actionVerify: (actionId: string) => `${API_BASE}/api/v1/actions/${encodeURIComponent(actionId)}/verify`,
  briefingProfiles: `${API_BASE}/api/v1/briefing-profiles`,
  briefingSessions: (params?: { limit?: number; offset?: number }) => {
    const query = new URLSearchParams()
    if (params?.limit) query.set('limit', String(params.limit))
    if (params?.offset) query.set('offset', String(params.offset))
    const qs = query.toString()
    return qs ? API_BASE + '/api/v1/briefing-sessions?' + qs : API_BASE + '/api/v1/briefing-sessions'
  },
  briefingSession: (sessionId: string) => API_BASE + '/api/v1/briefing-sessions/' + encodeURIComponent(sessionId),
  briefingSessionSpeech: (sessionId: string) => API_BASE + '/api/v1/briefing-sessions/' + encodeURIComponent(sessionId) + '/speech',
  briefingSessionSpeechPrepare: (sessionId: string, force = false) => API_BASE + '/api/v1/briefing-sessions/' + encodeURIComponent(sessionId) + '/speech/prepare' + (force ? '?force=true' : ''),
  briefingSessionSpeechPlay: (sessionId: string) => API_BASE + '/api/v1/briefing-sessions/' + encodeURIComponent(sessionId) + '/speech/play',
  briefingSessionSpeechStop: (sessionId: string) => API_BASE + '/api/v1/briefing-sessions/' + encodeURIComponent(sessionId) + '/speech/stop',
  briefingSessionEvidence: (sessionId: string, evidenceId: string) => API_BASE + '/api/v1/briefing-sessions/' + encodeURIComponent(sessionId) + '/evidence/' + encodeURIComponent(evidenceId),
  briefingSessionPresented: (sessionId: string) => API_BASE + '/api/v1/briefing-sessions/' + encodeURIComponent(sessionId) + '/presented',
  briefingHistory: `${API_BASE}/api/v1/briefings/history`,
  briefingTargets: `${API_BASE}/api/v1/briefings/targets`,
  briefingsGenerate: `${API_BASE}/api/v1/briefings/generate`,
  config: `${API_BASE}/api/v1/config`,
  diagnostics: `${API_BASE}/api/v1/diagnostics`,
  googleCalendarCalendars: `${API_BASE}/api/v1/google-calendar/calendars`,
  market: `${API_BASE}/api/v1/market`,
  mcpStatus: `${API_BASE}/api/v1/mcp/status`,
  llamaCppStatus: `${API_BASE}/api/v1/llama-cpp/status`,
  microsoftTodoStatus: `${API_BASE}/api/v1/microsoft-todo/status`,
  microsoftTodoLists: `${API_BASE}/api/v1/microsoft-todo/lists`,
  microsoftTodoAuthStart: `${API_BASE}/api/v1/microsoft-todo/auth/start`,
  microsoftTodoAuth: `${API_BASE}/api/v1/microsoft-todo/auth`,
  preflight: `${API_BASE}/api/v1/preflight`,
  reminders: `${API_BASE}/api/v1/reminders`,
  reminderTask: (id: string) => `${API_BASE}/api/v1/reminders/task?id=${encodeURIComponent(id)}`,
  remindersCompleted: `${API_BASE}/api/v1/reminders/completed`,
  remindersComplete: `${API_BASE}/api/v1/reminders/complete`,
  remindersUpdate: `${API_BASE}/api/v1/reminders/update`,
  remindersDelete: `${API_BASE}/api/v1/reminders/delete`,
  remindersReopen: `${API_BASE}/api/v1/reminders/reopen`,
  remindersSync: `${API_BASE}/api/v1/reminders/sync`,
  remindersDismiss: `${API_BASE}/api/v1/reminders/dismiss`,
  settings: `${API_BASE}/api/v1/settings`,
  status: `${API_BASE}/api/v1/status`,
  telemetryLatest: `${API_BASE}/api/v1/telemetry/latest`,
  telemetryRefresh: `${API_BASE}/api/v1/telemetry/refresh`,
  trigger: `${API_BASE}/api/v1/trigger`,
  voiceSpeak: `${API_BASE}/api/v1/voice/speak`,
  voiceCue: `${API_BASE}/api/v1/voice/cue`,
} as const
