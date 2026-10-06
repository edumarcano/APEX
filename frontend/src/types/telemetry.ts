export type TtsEngine = 'google' | 'kokoro' | 'pyttsx3'
export type LocalReasoningMode = 'none' | 'focused'

export interface SystemDiagnostics {
  cpu: number | null
  cpu_freq: number | null
  ram: number | null
  ram_used: number | null
  ram_total: number | null
  disk: number | null
  disk_used: number | null
  disk_total: number | null
}

export const DEFAULT_SYSTEM_DIAGNOSTICS: SystemDiagnostics = {
  cpu: null,
  cpu_freq: null,
  ram: null,
  ram_used: null,
  ram_total: null,
  disk: null,
  disk_used: null,
  disk_total: null,
}

export interface ActiveReminder {
  id: string
  note: string
  source: 'todo' | 'local'
  sync_state: 'synced' | 'pending' | 'unknown'
}

export interface ToolOutputItem {
  name: string
  status: string
  duration_ms: number
  output: unknown
}

export interface AgentMessage {
  role: 'user' | 'agent' | 'tool'
  content?: string
  tool_outputs?: ToolOutputItem[]
}

export type WeatherConditionArchetype =
  | 'clear_day'
  | 'clear_night'
  | 'clouds'
  | 'rain'
  | 'thunderstorm'

export interface WeatherTimelinePoint {
  label: string
  time: string
  temp_f: number | null
  condition: string
  archetype: WeatherConditionArchetype
  precip_prob: number
}

export type AgentRuntime = 'cloud' | 'local'
export type CloudEffort =
  | 'none'
  | 'minimal'
  | 'low'
  | 'medium'
  | 'high'
  | 'xhigh'
  | 'max'
export type CloudProvider = 'openrouter' | 'gemini'
export type LocalRuntime = 'llama_cpp'
export type HostedTool = 'google_search' | 'google_maps'

export type AgentKey = 'apex'

export type ToolCatalogGroupKind = 'apex_family' | 'mcp_server'

export interface ToolCatalogTool {
  name: string
  label: string
  description: string
  origin: 'native' | 'mcp'
  source_id: string
  apex_family: string | null
  risk: 'read' | 'write' | 'destructive'
  available: boolean
  unavailable_reason: string | null
  estimated_schema_tokens: number
  allowed_for_agent: boolean
}

export interface ToolCatalogGroup {
  id: string
  label: string
  kind: ToolCatalogGroupKind
  tool_count: number
  schema_token_subtotal: number
  tools: ToolCatalogTool[]
}

export interface ToolProfileMetadata {
  id: string
  name: string
  description: string
  tool_names: string[]
  built_in: boolean
  dynamic: boolean
}

export interface ToolCatalog {
  agent: AgentKey
  groups: ToolCatalogGroup[]
  tools: ToolCatalogTool[]
  profiles: ToolProfileMetadata[]
  default_profile_id: string
  default_profile_name: string
  default_selected_tool_names: string[]
  provider_hosted_tools: string[]
  context_window: number | null
  reserved_response_tokens: number | null
}

export interface ToolSelectionFailure {
  name: string
  code: string
  reason: string
}

export interface ToolSelectionDiagnostics {
  requested_tool_names: string[]
  offered_tool_names: string[]
  rejected_tool_names: string[]
  rejected_tools: ToolSelectionFailure[]
  selected_schema_tokens: number
  active_profile_id: string | null
  active_profile_name: string | null
}

export interface ToolTokenBreakdown {
  system_instructions: number
  conversation_history: number
  telemetry_context: number
  retrieved_context?: number
  selected_tool_schemas: number
  current_prompt: number
  total: number
  configured_context_window: number | null
  reserved_response_tokens: number | null
  remaining_estimated_capacity: number | null
  is_estimate: boolean
}

export interface ToolPreflightEstimate {
  agent: AgentKey
  selection: ToolSelectionDiagnostics
  breakdown: ToolTokenBreakdown
  warning: string | null
  can_proceed: boolean
}

export interface LocalContextUsage {
  estimated_prompt_tokens: number
  peak_prompt_tokens: number | null
  context_window: number
  history_messages_dropped: number
}

export type AgentAvailabilityStatus =
  | 'available'
  | 'busy'
  | 'configured'
  | 'verifying'
  | 'verified'
  | 'unauthorized'
  | 'model_unavailable'
  | 'rate_limited'
  | 'quota_exhausted'
  | 'billing_blocked'
  | 'provider_unreachable'
  | 'provider_error'
  | 'unknown'
  | 'disabled'
  | 'model_not_installed'
  | 'insufficient_ram'
  | 'cpu_overloaded'

export type AgentStability = 'stable' | 'preview' | 'experimental'
export type AgentStatusSource = 'configuration' | 'verification' | 'request' | 'runtime'

export interface AgentPricingMetadata {
  currency: 'USD'
  pricing_version: string
  billing_basis: 'standard' | 'local'
  input_per_million: number
  output_per_million: number
  cached_input_per_million: number | null
  long_context_threshold_tokens: number | null
  long_context_input_per_million: number | null
  long_context_output_per_million: number | null
  long_context_cached_input_per_million: number | null
}

export interface ModelCatalogEntry {
  model_id: string
  display_name: string
  provider: CloudProvider | LocalRuntime
  runtime: AgentRuntime
  stability: AgentStability
  hosted_capabilities: HostedTool[]
  pricing?: AgentPricingMetadata
  reasoning_options?: CloudEffort[] | null
  default_reasoning?: CloudEffort | null
  context_options?: number[] | null
  default_context_window?: number | null
  high_resource_context_options?: number[] | null
  maximum_context_window?: number | null
  reasoning_modes?: LocalReasoningMode[] | null
  default_reasoning_mode?: LocalReasoningMode | null
  supports_encrypted_reasoning?: boolean
  credentials_configured?: boolean
  status?: AgentAvailabilityStatus
  status_source?: AgentStatusSource
  status_checked_at?: string | null
  reason?: string | null
  active?: boolean
  loading?: boolean
  idle_unload_remaining_seconds?: number | null
  loaded_model?: LocalLoadedModelStatus | null
}

export interface LocalLoadedModelStatus {
  provider: 'llama_cpp'
  name: string
  model: string
  state: 'unloaded' | 'loading' | 'loaded' | 'sleeping' | 'failed' | 'unknown'
  context_window: number | null
  size_bytes: number | null
  size_vram_bytes: number | null
  processor: string | null
  context: string | null
  expires_at: string | null
}

/** The singular native Agent response returned by `/api/v1/cortex/agent`. */
export interface CortexAgent {
  key: AgentKey
  canonical_name?: string
  display_name: string
  description: string
  selected_model: string
  model_catalog: ModelCatalogEntry[]
}

export interface AgentInitialSelection {
  runtime: AgentRuntime
  agent: AgentKey
  modelId: string
  effort: CloudEffort | null
  sandboxMode?: boolean
}

export type ConnectorHealthStatus = 'healthy' | 'degraded' | 'unavailable' | 'disabled'
export type ConnectorFreshness = 'live' | 'fresh_cache' | 'stale' | 'none'

export interface ConnectorHealthEntry {
  name: string
  status: ConnectorHealthStatus
  freshness?: ConnectorFreshness
  reason_code?: string
  observed_at?: string | null
}

export interface TelemetryModuleEntry {
  name: string
  status: ConnectorHealthStatus
  freshness: ConnectorFreshness
  reason_code: string
  observed_at: string | null
  display_text: string
  data: Record<string, unknown>
}

export interface TelemetrySnapshot {
  snapshot_id: string
  collected_at: string
  modules: Record<string, TelemetryModuleEntry>
  sync_health_score: number
  connector_health: ConnectorHealthEntry[]
  failed_connectors: string[]
}

export interface TelemetryRefreshRequest {
  connectors?: string[] | null
  force?: boolean
}

export type PreflightOperation =
  | 'activate'
  | 'refresh_telemetry'
  | 'generate_briefing_session'
  | 'cortex_query'

export type PreflightWarningCode =
  | 'outside_configured_network'
  | 'network_trust_unknown'
  | 'running_on_battery'
  | 'rapid_connector_refresh'
  | 'high_resource_local_agent'

export type PreflightBlockerCode =
  | 'missing_credentials'
  | 'model_unreachable'
  | 'model_not_installed'
  | 'concurrent_local_execution'
  | 'insufficient_ram'
  | 'cpu_overloaded'
  | 'database_failure'
  | 'configuration_failure'
  | 'invalid_input'
  | 'model_load_failure'

export interface PreflightWarning {
  code: PreflightWarningCode
  message: string
}

export interface PreflightBlocker {
  code: PreflightBlockerCode
  message: string
}

export interface PreflightRequest {
  operation: PreflightOperation
  connectors?: string[] | null
  model_id?: string | null
  force?: boolean
  involves_cloud?: boolean
  acknowledged_warnings?: string[]
}

export interface PreflightResponse {
  warnings: PreflightWarning[]
  blockers: PreflightBlocker[]
  can_proceed: boolean
}

export type SystemState = 'idle' | 'loading' | 'success' | 'error'

export interface MarketDailyBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface MarketTickerItem {
  symbol: string
  price: number | null
  change: number | null
  change_percent: number | null
  status: ConnectorHealthStatus
  freshness: ConnectorFreshness
  reason_code: string
  observed_at: string | null
  close_date: string | null
  last_successful_fetch_date: string | null
  last_attempt_date: string | null
  next_attempt_date: string | null
  history: MarketDailyBar[]
  period_return_percent: number | null
  period_low: number | null
  period_high: number | null
  volume_ratio: number | null
}

export interface MarketResponse {
  status: ConnectorHealthStatus
  freshness: ConnectorFreshness
  reason_code: string
  observed_at: string | null
  collection_revision: number
  tickers: MarketTickerItem[]
}

export interface ApexDataState {
  activeReminders: ActiveReminder[]
  reminderSourceState?: 'live' | 'stale' | 'unavailable'
  remindersLoadState: 'loading' | 'loaded' | 'unavailable'
  demoModeActive: boolean
  devModeActive: boolean
  defaultAgent?: AgentKey
  agentInitialSelection?: AgentInitialSelection
  voiceMode?: 'off' | 'manual' | 'automatic'
  agentQueriesEnabled?: boolean
  marketEnabled: boolean
}
