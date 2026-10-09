export type ParameterChange = { scale: number } | { native_value: number }
export type Pacing = {
  mode?: 'external' | 'spontaneous' | 'single_beat'
  frequency_hz: number
  stimulus_duration_ms: number
  stimulus_strength_nA: number
  offset_ms: number
  cm_pf: number
}
export type Model = {
  id: string
  display_name: string
  category: string
  developmental_stage: string
  backend: string
  status: string
  status_reason?: string
  source_url: string
  source_revision: string
  sha256: string | null
  publication: { authors: string; year: number; doi: string | null }
  license: { status: string; notes: string }
  default_cell_type: string
  default_pacing: Pacing
  parameters: Record<string, string>
  currents: Record<string, string>
  default_options?: Record<string, number>
  model_options?: Record<string, {label: string; unit: string; min: number; max: number; step: number}>
  parameter_metadata?: Record<string, {native_name: string; native_unit: string; native_baseline: number; training_min?: number; training_max?: number}>
}
export type SimConfig = {
  model_id: string
  duration_ms: number
  pacing?: Pacing
  prepace_beats: number
  parameters: Record<string, ParameterChange>
  model_options: Record<string, number>
  include_currents: string[]
  auto_rescue: boolean
}
export type Result = {
  model_id: string
  model_version: string
  backend: string
  settings_requested: SimConfig
  settings_actual: Record<string, unknown>
  time_ms: number[]
  voltage_mv: number[]
  calcium: { values?: number[]; unit?: string; native_name?: string }
  currents: Record<string, { values: number[]; unit: string; native_name: string; native_unit: string; conversion: string }>
  metrics: Record<string, unknown> & { last_valid_beat?: Record<string, unknown>; valid?: boolean }
  warnings: string[]
  provenance: Record<string, unknown>
}
