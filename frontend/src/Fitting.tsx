import { useEffect, useRef, useState } from 'react'
import Plotly from 'plotly.js-dist-min'
import type { Result } from './types'
import { API } from './api'

const NAMES = ['GNa', 'GNaL_b', 'Gto_b', 'GKr_b', 'GKs_b', 'GK1_b', 'Gncx_b', 'Pnak_b', 'PCa_b']
type FitTrace = { column: string; time_ms: number[]; target_mv: number[]; emulator_mv: number[]; rmse_mv: number; upstroke_time_ms: number; time_offset_ms: number; parameters: Record<string, number>; parameter_table: { name: string; baseline: number; fitted: number; percent_change_from_baseline: number; training_min: number; training_max: number; at_training_bound: boolean }[] }
type Fit = { mode: string; traces: { reference: FitTrace; mutant?: FitTrace }; settings: Record<string, unknown>; provenance: Record<string, unknown>; warnings: string[] }
type Validation = { mapped_count: number; ignored_parameters: string[]; mechanistic_result: Result; warning: string }

function saveJson(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url)
}

function Overlay({ fit, validation }: { fit: FitTrace; validation: Validation | null }) {
  const node = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!node.current) return
    const element = node.current
    const lines: Plotly.Data[] = [
      { x: fit.time_ms, y: fit.target_mv, type: 'scattergl', mode: 'lines', name: 'Experimental target', line: { color: '#243f4a', width: 2 } },
      { x: fit.time_ms, y: fit.emulator_mv, type: 'scattergl', mode: 'lines', name: 'Grandits fit', line: { color: '#d68453', width: 2.5 } },
    ]
    if (validation) {
      const result = validation.mechanistic_result
      const upstroke = Number(result.metrics.last_valid_beat?.upstroke_time_ms ?? 0)
      lines.push({ x: result.time_ms.map(time => time - upstroke), y: result.voltage_mv, type: 'scattergl', mode: 'lines', name: 'ToR validation', line: { color: '#2d8291', width: 2.5 } })
    }
    void Plotly.react(element, lines, {
      height: 380, margin: { l: 62, r: 20, t: 20, b: 52 },
      paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      xaxis: { title: { text: 'Time from upstroke (ms)' }, gridcolor: '#dfe7e8' },
      yaxis: { title: { text: 'Voltage (mV)' }, gridcolor: '#dfe7e8' },
      legend: { orientation: 'h', x: 0, y: 1.16 }, hovermode: 'x unified',
    }, { responsive: true, displaylogo: false })
    return () => { Plotly.purge(element) }
  }, [fit, validation])
  return <div ref={node} role="img" aria-label="Experimental, emulator, and mechanistic voltage overlay" />
}

export default function Fitting() {
  const [csvText, setCsvText] = useState('')
  const [fileName, setFileName] = useState('')
  const [columns, setColumns] = useState<string[]>([])
  const [timeColumn, setTimeColumn] = useState('')
  const [timeUnit, setTimeUnit] = useState<'ms' | 's'>('ms')
  const [referenceColumn, setReferenceColumn] = useState('')
  const [mutantColumn, setMutantColumn] = useState('')
  const [traceMode, setTraceMode] = useState<'voltage_mv' | 'dff' | 'shape'>('voltage_mv')
  const [dfFor100, setDfFor100] = useState(0.29)
  const [restMv, setRestMv] = useState(-85)
  const [epochs, setEpochs] = useState(150)
  const [maxPoints, setMaxPoints] = useState(500)
  const [fitNames, setFitNames] = useState<string[]>(NAMES)
  const [variableNames, setVariableNames] = useState<string[]>(['PCa_b', 'GKr_b', 'GKs_b', 'GK1_b'])
  const [directions, setDirections] = useState<Record<string, string>>({})
  const [limits, setLimits] = useState<Record<string, number>>({})
  const [fit, setFit] = useState<Fit | null>(null)
  const [selectedRole, setSelectedRole] = useState<'reference' | 'mutant'>('reference')
  const [validation, setValidation] = useState<Validation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function loadFile(file?: File) {
    if (!file) return
    if (file.size > 2_000_000) { setError('CSV files are limited to 2 MB.'); return }
    const content = await file.text()
    const header = content.replace(/^\ufeff/, '').split(/\r?\n/, 1)[0].split(/[,;\t]/).map(value => value.trim().replace(/^"|"$/g, ''))
    setCsvText(content); setFileName(file.name); setColumns(header)
    const time = header.find(name => name.toLowerCase().startsWith('time')) ?? header[0] ?? ''
    const traces = header.filter(name => name !== time)
    setTimeColumn(time); setReferenceColumn(traces[0] ?? ''); setMutantColumn(traces[1] ?? '')
    setFit(null); setValidation(null); setError('')
  }

  async function runFit() {
    setBusy(true); setError(''); setValidation(null)
    try {
      const response = await fetch(`${API}/fitting/grandits`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        csv_text: csvText, time_column: timeColumn, time_unit: timeUnit, reference_column: referenceColumn,
        mutant_column: mutantColumn || null, trace_mode: traceMode, df_for_100mv: dfFor100, rest_mv: restMv,
        fit_parameters: fitNames, mutant_variable_parameters: variableNames,
        directions, mutant_change_limits_pct: limits, epochs, max_points: maxPoints, seed: 7,
      }) })
      const value = await response.json()
      if (!response.ok) throw new Error(value.detail ?? 'Fit failed')
      setFit(value); setSelectedRole('reference')
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  async function validate() {
    if (!fit) return
    const selectedTrace = fit.traces[selectedRole]
    if (!selectedTrace) return
    setBusy(true); setError('')
    try {
      const response = await fetch(`${API}/fitting/validate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ grandits_parameters: selectedTrace.parameters, duration_ms: 1000, prepace_beats: 50 }) })
      const value = await response.json()
      if (!response.ok) throw new Error(value.detail ?? 'Validation failed')
      setValidation(value)
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  const selected = fit?.traces[selectedRole]
  const displayedValidation = validation && selected ? validation : null
  return <main className="fitting-page"><div className="page-heading"><div><p className="eyebrow">03 / FITTING</p><h1>Grandits inverse fitting</h1><p>Fit a voltage-like CSV trace, then run an independent nine-parameter ToR simulation.</p></div></div>
    {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
    <div className="fitting-layout"><aside className="fit-controls"><section><h2>1 · Data</h2><label className="upload-zone"><span>{fileName || 'Choose a CSV file'}</span><small>Numeric data only · up to 2 MB</small><input type="file" accept=".csv,text/csv" onChange={event => { void loadFile(event.target.files?.[0]) }} /></label>
      {columns.length > 0 && <><label className="fit-field">Time column<select value={timeColumn} onChange={event => setTimeColumn(event.target.value)}>{columns.map(name => <option key={name}>{name}</option>)}</select></label><label className="fit-field">Time unit<select value={timeUnit} onChange={event => setTimeUnit(event.target.value as 'ms' | 's')}><option value="ms">Milliseconds</option><option value="s">Seconds</option></select></label><label className="fit-field">Reference trace<select value={referenceColumn} onChange={event => setReferenceColumn(event.target.value)}>{columns.filter(name => name !== timeColumn).map(name => <option key={name}>{name}</option>)}</select></label><label className="fit-field">Mutant trace<select value={mutantColumn} onChange={event => setMutantColumn(event.target.value)}><option value="">None · reference only</option>{columns.filter(name => name !== timeColumn && name !== referenceColumn).map(name => <option key={name}>{name}</option>)}</select></label></>}
    </section><section><h2>2 · Calibration</h2><label className="fit-field">Trace type<select value={traceMode} onChange={event => setTraceMode(event.target.value as 'voltage_mv' | 'dff' | 'shape')}><option value="voltage_mv">Voltage (mV)</option><option value="dff">dF/F</option><option value="shape">Shape only</option></select></label>{traceMode === 'dff' && <><label className="fit-field">dF/F for 100 mV<input type="number" min="0.001" max="10" step="0.01" value={dfFor100} onChange={event => setDfFor100(Number(event.target.value))} /></label><label className="fit-field">Resting voltage (mV)<input type="number" min="-150" max="50" value={restMv} onChange={event => setRestMv(Number(event.target.value))} /></label></>}</section>
    <section><h2>3 · Fit settings</h2><label className="fit-field">Optimizer epochs<input type="number" min="10" max="400" value={epochs} onChange={event => setEpochs(Number(event.target.value))} /></label><label className="fit-field">Maximum fit points<input type="number" min="100" max="2000" value={maxPoints} onChange={event => setMaxPoints(Number(event.target.value))} /></label><details><summary>Reference conductances to fit</summary><div className="fit-checkboxes">{NAMES.map(name => <label key={name}><input type="checkbox" checked={fitNames.includes(name)} onChange={event => setFitNames(old => event.target.checked ? [...old, name] : old.filter(item => item !== name))} />{name}</label>)}</div></details>{mutantColumn && <details open><summary>Mutant changes</summary><div className="mutant-table"><div className="mutant-header"><span>Conductance</span><span>Direction</span><span>Max ±%</span></div>{NAMES.map(name => <div className="mutant-row" key={name}><label><input type="checkbox" checked={variableNames.includes(name)} onChange={event => setVariableNames(old => event.target.checked ? [...old, name] : old.filter(item => item !== name))} />{name}</label><select value={directions[name] ?? 'free'} onChange={event => setDirections(old => ({ ...old, [name]: event.target.value }))} disabled={!variableNames.includes(name)}><option value="free">Free</option><option value="up">Up</option><option value="down">Down</option></select><input type="number" min="0" max="200" value={limits[name] ?? 100} disabled={!variableNames.includes(name)} onChange={event => setLimits(old => ({ ...old, [name]: Number(event.target.value) }))} /></div>)}</div></details>}</section>
    <button className="primary-button" disabled={!csvText || busy || !referenceColumn || fitNames.length === 0} onClick={runFit}>{busy ? 'Working…' : 'Run Grandits fit'} <span>→</span></button></aside>
    <section className="fit-results">{fit && selected ? <><div className="fit-results-head"><div><p className="eyebrow">FIT RESULT</p><h2>{selected.column}</h2><p>Emulator RMSE: {selected.rmse_mv.toFixed(2)} mV · time offset {selected.time_offset_ms.toFixed(1)} ms</p></div><button onClick={() => saveJson('grandits-fit.json', fit)}>↓ Fit JSON</button></div>
      {fit.traces.mutant && <div className="role-toggle"><button className={selectedRole === 'reference' ? 'active' : ''} onClick={() => { setSelectedRole('reference'); setValidation(null) }}>Reference</button><button className={selectedRole === 'mutant' ? 'active' : ''} onClick={() => { setSelectedRole('mutant'); setValidation(null) }}>Mutant</button></div>}
      <div className="chart-card"><Overlay fit={selected} validation={displayedValidation} /></div><div className="fit-validation"><div><h3>Mechanistic validation</h3><p>Apply all nine fitted values to ToR-ORd native base variables. The ToR trace is independent of the emulator fit.</p></div><button className="primary-button" disabled={busy} onClick={validate}>{busy ? 'Working…' : 'Validate in ToR'} →</button></div>
      {validation && <div className="validation-status"><strong>{validation.mapped_count}/9 parameters applied</strong><span>{validation.warning}</span><button onClick={() => saveJson('tor-validation.json', validation)}>↓ Validation JSON</button></div>}
      <div className="chart-card"><h3>Fitted conductances</h3><div className="table-scroll"><table><thead><tr><th>Grandits input</th><th>Baseline</th><th>Fitted</th><th>Change</th><th>Training range</th></tr></thead><tbody>{selected.parameter_table.map(row => <tr key={row.name}><th>{row.name}</th><td>{row.baseline.toPrecision(5)}</td><td>{row.fitted.toPrecision(5)}</td><td>{row.percent_change_from_baseline.toFixed(1)}%</td><td>{row.training_min.toPrecision(3)} – {row.training_max.toPrecision(3)}{row.at_training_bound ? ' · bound' : ''}</td></tr>)}</tbody></table></div></div>
      {fit.warnings.map(warning => <div className="warning" key={warning}>{warning}</div>)}</> : <div className="empty-state"><div className="empty-wave">∿</div><h3>Fit results will appear here</h3><p>Choose a CSV with a time column and at least one voltage-like trace.</p></div>}</section></div>
  </main>
}
