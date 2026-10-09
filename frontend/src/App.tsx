import { useEffect, useRef, useState } from 'react'
import Plotly from 'plotly.js-dist-min'
import type { Model, Result, SimConfig, Pacing, ParameterChange } from './types'
import Fitting from './Fitting'
import { API } from './api'

type View = 'simulator' | 'compare' | 'fitting' | 'models'
const COLORS = ['#d68453', '#3b8290', '#8f6cbd', '#a5a752']

async function jsonRequest<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const value = await response.json()
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail))
  return value as T
}

function defaultConfig(model: Model): SimConfig {
  return {
    model_id: model.id,
    duration_ms: model.backend === 'grandits' ? 500 : model.category === 'pacemaker' ? 3000 : 1000,
    pacing: model.default_pacing,
    prepace_beats: model.backend === 'grandits' || model.backend === 'external_compiled' || model.backend === 'herrera_octave' ? 0 : model.default_pacing.mode === 'spontaneous' ? 5 : 50,
    parameters: {},
    model_options: { ...(model.default_options ?? {}) },
    include_currents: model.backend === 'grandits' ? [] : ['INa', 'IKr', 'ICaL'].filter(name => model.currents[name]),
    auto_rescue: false,
  }
}

function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

function resultCsv(result: Result): string {
  const currents = Object.keys(result.currents)
  const header = ['time_ms', 'voltage_mv', ...currents.map(name => `${name}_${result.currents[name].unit}`)]
  const rows = result.time_ms.map((time, index) => [time, result.voltage_mv[index], ...currents.map(name => result.currents[name].values[index])].join(','))
  return [header.join(','), ...rows].join('\n')
}

function Plot({ traces, yTitle, height = 350 }: { traces: { x: number[]; y: number[]; name: string; color: string }[]; yTitle: string; height?: number }) {
  const element = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!element.current || !traces.length) return
    const node = element.current
    void Plotly.react(node, traces.map(trace => ({ x: trace.x, y: trace.y, name: trace.name, type: 'scattergl', mode: 'lines', line: { color: trace.color, width: 2.4 } })), {
      height,
      margin: { l: 63, r: 20, t: 16, b: 54 },
      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      font: { family: 'Inter, system-ui, sans-serif', color: '#23404a', size: 13 },
      xaxis: { title: { text: 'Time (ms)' }, gridcolor: '#dfe7e8', zeroline: false },
      yaxis: { title: { text: yTitle }, gridcolor: '#dfe7e8', zeroline: false },
      legend: { orientation: 'h', x: 0, y: 1.15 },
      hovermode: 'x unified',
    }, { responsive: true, displaylogo: false, toImageButtonOptions: { format: 'svg' } })
    return () => { Plotly.purge(node) }
  }, [traces, yTitle, height])
  return <div ref={element} className="plot" role="img" aria-label={`${yTitle} plot`} />
}

function ModelSelect({ models, value, onChange }: { models: Model[]; value: string; onChange: (id: string) => void }) {
  const categories = ['ventricular', 'atrial', 'pacemaker']
  return <select value={value} onChange={event => onChange(event.target.value)} aria-label="Cardiac model">
    {categories.map(category => <optgroup key={category} label={category === 'pacemaker' ? 'Pacemaker / SAN' : category[0].toUpperCase() + category.slice(1)}>
      {models.filter(model => model.category === category).map(model => <option key={model.id} value={model.id} disabled={model.status !== 'enabled'}>
        {model.display_name}{model.status === 'enabled' ? '' : ' · unavailable'}
      </option>)}
    </optgroup>)}
  </select>
}

function NumberField({ label, value, min, max, step = 1, unit, onChange }: { label: string; value: number; min?: number; max?: number; step?: number; unit?: string; onChange: (value: number) => void }) {
  return <label className="field"><span>{label}</span><span className="input-unit"><input type="number" value={value} min={min} max={max} step={step} onChange={event => onChange(Number(event.target.value))} />{unit && <small>{unit}</small>}</span></label>
}

function ConfigEditor({ models, config, detail, onChange, compact = false }: { models: Model[]; config: SimConfig; detail: Model | null; onChange: (value: SimConfig) => void; compact?: boolean }) {
  function patch(value: Partial<SimConfig>) { onChange({ ...config, ...value }) }
  function patchPacing(value: Partial<Pacing>) { patch({ pacing: { ...config.pacing!, ...value } }) }
  function selectModel(id: string) {
    const model = models.find(item => item.id === id)
    if (model) onChange(defaultConfig(model))
  }
  const mode = detail?.default_pacing.mode
  return <div className="config-editor">
    <label className="field"><span>Model</span><ModelSelect models={models} value={config.model_id} onChange={selectModel} /></label>
    {detail && <div className="model-inline"><span>{detail.default_cell_type.replaceAll('_', ' ')}</span><span className="dot">•</span><span>{detail.backend}</span><span className="dot">•</span><span>{detail.source_revision.slice(0, 10)}</span></div>}
    <div className="form-section"><h3>Protocol</h3>
      <NumberField label="Duration" value={config.duration_ms} min={50} max={detail?.backend === 'grandits' ? 500 : 20000} step={100} unit="ms" onChange={duration_ms => patch({ duration_ms })} />
      {mode === 'external' && <>
        <NumberField label="Frequency" value={config.pacing?.frequency_hz ?? 1} min={0.1} max={20} step={0.1} unit="Hz" onChange={frequency_hz => patchPacing({ frequency_hz })} />
        <NumberField label="Stimulus strength" value={config.pacing?.stimulus_strength_nA ?? 0} min={0} max={100} step={0.05} unit="nA" onChange={stimulus_strength_nA => patchPacing({ stimulus_strength_nA })} />
        <NumberField label="Pulse duration" value={config.pacing?.stimulus_duration_ms ?? 0} min={0} max={20} step={0.1} unit="ms" onChange={stimulus_duration_ms => patchPacing({ stimulus_duration_ms })} />
        <NumberField label="Offset" value={config.pacing?.offset_ms ?? 0} min={0} max={20000} step={10} unit="ms" onChange={offset_ms => patchPacing({ offset_ms })} />
        <NumberField label="Capacitance" value={config.pacing?.cm_pf ?? 50} min={1} max={500} step={1} unit="pF" onChange={cm_pf => patchPacing({ cm_pf })} />
      </>}
      {mode === 'single_beat' && <p className="small-note">Single-beat surrogate. Pacing and ionic currents are unavailable.</p>}
      {mode === 'spontaneous' && <p className="small-note">Intrinsic rhythm without an external stimulus.</p>}
      {mode !== 'single_beat' && <NumberField label={mode === 'spontaneous' ? 'Warm-up seconds' : 'Prepace beats'} value={config.prepace_beats} min={0} max={100} unit={mode === 'spontaneous' ? 's' : undefined} onChange={prepace_beats => patch({ prepace_beats })} />}
    </div>
    {detail && detail.model_options && <div className="form-section"><h3>Model options</h3>
      {Object.entries(detail.model_options).map(([name, option]) => <NumberField key={name} label={option.label} value={config.model_options[name] ?? detail.default_options?.[name] ?? option.min} min={option.min} max={option.max} step={option.step} unit={option.unit} onChange={value => patch({ model_options: { ...config.model_options, [name]: value } })} />)}
    </div>}
    {detail && <div className="form-section"><h3>Parameter scales <span className="h3-note">native baseline = 100%</span></h3>
      {Object.entries(detail.parameter_metadata ?? {}).map(([canonical, meta]) => {
        const change = config.parameters[canonical]
        const scale = change && 'scale' in change ? change.scale : 1
        const native = change && 'native_value' in change ? change.native_value : undefined
        return <div className="parameter" key={canonical}>
          <div className="parameter-head"><strong>{canonical}</strong><span>{native === undefined ? `${Math.round(scale * 100)}%` : 'native'}</span></div>
          <input type="range" min="0" max="200" step="5" value={native === undefined ? scale * 100 : 100} onChange={event => {
            const next = { ...config.parameters }; const value = Number(event.target.value) / 100
            if (value === 1) delete next[canonical]; else next[canonical] = { scale: value }
            patch({ parameters: next })
          }} aria-label={`${canonical} scale percent`} />
          <div className="parameter-native">{meta.native_name} · {meta.native_baseline.toPrecision(5)} {meta.native_unit}</div>
          {!compact && <details><summary>Advanced native value</summary><label className="field"><span>{canonical} native</span><input type="number" value={native ?? meta.native_baseline * scale} step="any" onChange={event => {
            const next = { ...config.parameters }; next[canonical] = { native_value: Number(event.target.value) } as ParameterChange; patch({ parameters: next })
          }} /></label></details>}
        </div>
      })}
    </div>}
    {detail && Object.keys(detail.currents).length > 0 && !compact && <div className="form-section"><h3>Ionic currents</h3><div className="current-checks">
      {Object.keys(detail.currents).map(name => <label key={name}><input type="checkbox" checked={config.include_currents.includes(name)} onChange={event => patch({ include_currents: event.target.checked ? [...config.include_currents, name] : config.include_currents.filter(item => item !== name) })} />{name}</label>)}
    </div></div>}
  </div>
}

function Metrics({ result }: { result: Result }) {
  const item = result.metrics.mode === 'paced' ? result.metrics.last_valid_beat : result.metrics
  if (!item || item.valid === false) return <p className="empty-inline">No measurable full beat in this trace.</p>
  const keys = result.metrics.mode === 'paced'
    ? [['apd90_ms', 'APD90', 'ms'], ['amplitude_mv', 'Amplitude', 'mV'], ['dvdt_max_mv_per_ms', 'Max dV/dt', 'mV/ms'], ['resting_mv', 'Resting Vm', 'mV']]
    : [['cycle_length_ms', 'Cycle length', 'ms'], ['rate_bpm', 'Rate', 'bpm'], ['maximum_diastolic_potential_mv', 'MDP', 'mV'], ['dvdt_max_mv_per_ms', 'Max dV/dt', 'mV/ms']]
  return <div className="metrics-grid">{keys.map(([key, label, unit]) => <div className="metric" key={key}><span>{label}</span><strong>{typeof item[key] === 'number' ? (item[key] as number).toFixed(1) : '—'}</strong><small>{unit}</small></div>)}</div>
}

function ModelInfo({ model }: { model: Model }) {
  return <details className="about"><summary>About this model</summary><div className="about-grid">
    <span>Source</span><a href={model.source_url} target="_blank" rel="noreferrer">Pinned source ↗</a>
    <span>Revision</span><code>{model.source_revision}</code>
    <span>SHA-256</span><code className="hash">{model.sha256 ?? 'Unavailable'}</code>
    <span>Publication</span><span>{model.publication.authors} ({model.publication.year}){model.publication.doi && <> · <a href={`https://doi.org/${model.publication.doi}`} target="_blank" rel="noreferrer">DOI ↗</a></>}</span>
    <span>License</span><span>{model.license.status}</span>
    <span>Notes</span><span>{model.license.notes}</span>
  </div></details>
}

export default function App() {
  const [models, setModels] = useState<Model[]>([])
  const [view, setView] = useState<View>('simulator')
  const [config, setConfig] = useState<SimConfig | null>(null)
  const [detail, setDetail] = useState<Model | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [compareConfigs, setCompareConfigs] = useState<SimConfig[]>([])
  const [compareDetails, setCompareDetails] = useState<Record<string, Model>>({})
  const [compareResults, setCompareResults] = useState<Result[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => { void jsonRequest<Model[]>(`${API}/models`).then(items => {
    setModels(items)
    const first = items.find(item => item.id === 'torord_dyncl_endo' && item.status === 'enabled') ?? items.find(item => item.status === 'enabled')
    if (first) { setConfig(defaultConfig(first)); setCompareConfigs([defaultConfig(first), defaultConfig(items.find(item => item.id === 'ord_2011' && item.status === 'enabled') ?? first)]) }
  }).catch(err => setError(`Model catalog unavailable: ${err.message}`)) }, [])
  useEffect(() => { if (config) void jsonRequest<Model>(`${API}/models/${config.model_id}`).then(setDetail).catch(err => setError(err.message)) }, [config?.model_id])
  useEffect(() => { compareConfigs.forEach(item => {
    if (!compareDetails[item.model_id]) void jsonRequest<Model>(`${API}/models/${item.model_id}`).then(value => setCompareDetails(old => ({ ...old, [item.model_id]: value }))).catch(err => setError(err.message))
  }) }, [compareConfigs.map(item => item.model_id).join(',')])

  async function runOne() {
    if (!config) return
    setBusy(true); setError('')
    try { setResult(await jsonRequest<Result>(`${API}/simulate`, config)) } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  async function runCompare() {
    setBusy(true); setError('')
    try { const response = await jsonRequest<{ simulations: Result[] }>(`${API}/compare`, { simulations: compareConfigs }); setCompareResults(response.simulations) } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  function updateComparison(index: number, value: SimConfig) { setCompareConfigs(previous => previous.map((item, i) => i === index ? value : item)) }

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">∿</span><div><strong>Cardiac AP</strong><small>Research workspace</small></div></div><nav aria-label="Main navigation">
      {(['simulator', 'compare', 'fitting', 'models'] as View[]).map(item => <button key={item} className={view === item ? 'active' : ''} onClick={() => { setView(item); setError('') }}>{item[0].toUpperCase() + item.slice(1)}</button>)}
    </nav><span className="research-tag">Research exploration only</span></header>
    {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
    {view === 'simulator' && config && <main className="workspace"><aside className="controls"><div className="panel-title"><p className="eyebrow">01 / SIMULATOR</p><h1>Configure a run</h1></div><button className="primary-button" onClick={runOne} disabled={busy || detail?.status !== 'enabled'}>{busy ? 'Running…' : 'Run simulation'} <span>→</span></button><ConfigEditor models={models} config={config} detail={detail} onChange={setConfig} /></aside>
      <section className="results"><div className="results-heading"><div><p className="eyebrow">ACTION POTENTIAL</p><h2>{result ? models.find(item => item.id === result.model_id)?.display_name : 'Trace preview'}</h2></div>{result && <div className="export-actions"><button onClick={() => download(`${result.model_id}.json`, JSON.stringify(result, null, 2), 'application/json')}>↓ JSON</button><button onClick={() => download(`${result.model_id}.csv`, resultCsv(result), 'text/csv')}>↓ CSV</button></div>}</div>
        {result ? <><div className="chart-card"><Plot traces={[{ x: result.time_ms, y: result.voltage_mv, name: 'Vm', color: COLORS[0] }]} yTitle="Membrane potential (mV)" /></div><Metrics result={result} />
          {result.warnings.map(warning => <div className="warning" key={warning}>{warning}</div>)}
          {result.calcium.values && <div className="chart-card"><h3>Calcium · {result.calcium.native_name}</h3><Plot traces={[{ x: result.time_ms, y: result.calcium.values, name: 'Ca', color: COLORS[1] }]} yTitle={`Calcium (${result.calcium.unit})`} height={260} /></div>}
          {Object.keys(result.currents).length > 0 && <div className="chart-card"><h3>Ionic currents</h3><Plot traces={Object.entries(result.currents).map(([name, current], index) => ({ x: result.time_ms, y: current.values, name: `${name} (${current.unit})`, color: COLORS[index % COLORS.length] }))} yTitle="Current (display units)" height={310} /><div className="current-legend">{Object.entries(result.currents).map(([name, current]) => <span key={name}>{name}: {current.native_name} · {current.native_unit} → {current.unit}</span>)}</div></div>}
          <details className="about"><summary>Protocol and applied parameters</summary><pre>{JSON.stringify({ requested: result.settings_requested, actual: result.settings_actual }, null, 2)}</pre></details></> : <div className="empty-state"><div className="empty-wave">∿</div><h3>Ready to simulate</h3><p>Choose a model and protocol, then run it to inspect voltage, biomarkers, and currents.</p></div>}
        {detail && <ModelInfo model={detail} />}
      </section></main>}
    {view === 'compare' && <main className="compare-page"><div className="page-heading"><div><p className="eyebrow">02 / COMPARE</p><h1>Overlay model runs</h1><p>Compare 2–4 traces with each model’s protocol and parameters shown separately.</p></div><button className="primary-button" onClick={runCompare} disabled={busy || compareConfigs.length < 2}>{busy ? 'Running…' : 'Run comparison'} →</button></div>
      <div className="comparison-editors">{compareConfigs.map((item, index) => <section className="comparison-card" key={index}><div className="comparison-card-title"><strong>Run {index + 1}</strong>{compareConfigs.length > 2 && <button onClick={() => setCompareConfigs(previous => previous.filter((_, i) => i !== index))}>Remove</button>}</div><ConfigEditor models={models} config={item} detail={compareDetails[item.model_id] ?? null} onChange={value => updateComparison(index, value)} compact /></section>)}</div>
      {compareConfigs.length < 4 && <button className="add-button" onClick={() => setCompareConfigs(previous => [...previous, defaultConfig(models.find(item => item.id === previous[0]?.model_id) ?? models[0])])}>+ Add run</button>}
      {compareResults.length > 0 && <><div className="chart-card"><div className="chart-heading"><h2>Voltage overlay</h2><button onClick={() => download('cardiac-comparison.json', JSON.stringify(compareResults, null, 2), 'application/json')}>↓ JSON</button></div><Plot traces={compareResults.map((item, index) => ({ x: item.time_ms, y: item.voltage_mv, name: `${models.find(model => model.id === item.model_id)?.display_name ?? item.model_id} · run ${index + 1}`, color: COLORS[index] }))} yTitle="Membrane potential (mV)" height={450} /></div><div className="comparison-summary">{compareResults.map((item, index) => <article key={index}><h3><span style={{ background: COLORS[index] }} />Run {index + 1}: {models.find(model => model.id === item.model_id)?.display_name}</h3><Metrics result={item} /><p>Revision {item.model_version.slice(0, 10)} · {String((item.settings_actual.pacing as Pacing)?.mode)} pacing · {Object.keys(item.settings_requested.parameters).length} changed parameters</p><details><summary>Requested and actual settings</summary><pre>{JSON.stringify({ requested: item.settings_requested, actual: item.settings_actual }, null, 2)}</pre></details></article>)}</div><p className="comparison-caveat">Absolute conductance values are not directly comparable across different model formulations.</p></>}
    </main>}
    {view === 'fitting' && <Fitting />}
    {view === 'models' && <main className="models-page"><div className="page-heading"><div><p className="eyebrow">04 / MODEL CATALOG</p><h1>Scientific sources and availability</h1><p>Every model reports its pinned revision, license status, runtime status, and exact blocker when unavailable.</p></div></div>
      <div className="model-catalog">{models.map(model => <article className="model-card" key={model.id}>
        <div className="model-card-head"><div><span className="model-category">{model.category} · {model.developmental_stage}</span><h2>{model.display_name}</h2></div><span className={`status ${model.status}`}>{model.status}</span></div>
        <dl><dt>Backend</dt><dd>{model.backend}</dd><dt>Variant</dt><dd>{model.default_cell_type.replaceAll('_', ' ')}</dd><dt>Revision</dt><dd><code>{model.source_revision}</code></dd><dt>License</dt><dd>{model.license.status}</dd></dl>
        {model.status_reason && <p className="model-blocker">{model.status_reason}</p>}
        <div className="model-card-links"><a href={model.source_url} target="_blank" rel="noreferrer">Pinned source ↗</a>{model.publication.doi && <a href={`https://doi.org/${model.publication.doi}`} target="_blank" rel="noreferrer">Publication ↗</a>}</div>
      </article>)}</div>
    </main>}
    <footer>Model versions, units, applied parameters, and requested versus actual pacing are preserved in every result. This tool is for research exploration, not clinical diagnosis.</footer>
  </div>
}
