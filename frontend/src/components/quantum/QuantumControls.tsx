import { useId, type CSSProperties } from 'react'

interface BaseProps {
  label: string
  hint?: string
  disabled?: boolean
}

const labelClass = 'mb-1.5 flex items-baseline justify-between gap-2 text-xs font-medium text-mist-300'

export function QuantumSelect({
  label,
  hint,
  disabled = false,
  value,
  onChange,
  options,
}: BaseProps & {
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string; disabled?: boolean }[]
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        <span>{label}</span>
        {hint && <span className="text-[11px] font-normal text-mist-600">{hint}</span>}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="w-full appearance-none rounded-lg border border-forest-600 bg-forest-800 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/50 focus-visible:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}

export function QuantumSlider({
  label,
  hint,
  disabled = false,
  value,
  onChange,
  step = 0.05,
  display,
  min = 0,
  max = 1,
}: BaseProps & {
  value: number
  onChange: (value: number) => void
  step?: number
  display?: string
  min?: number
  max?: number
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        <span>{label}</span>
        <span className="font-mono text-[11px] text-ai-300">{display ?? value.toFixed(2)}</span>
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="quantum-slider w-full"
        style={{ '--quantum-fill': `${((value - min) / (max - min)) * 100}%` } as CSSProperties}
      />
      {hint && <p className="mt-1 text-[11px] text-mist-600">{hint}</p>}
    </div>
  )
}

export function QuantumNumberInput({
  label,
  hint,
  disabled = false,
  value,
  onChange,
  min,
  max,
  unit,
  step = 1,
}: BaseProps & {
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  unit?: string
  step?: number
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        <span>{label}</span>
        {hint && <span className="text-[11px] font-normal text-mist-600">{hint}</span>}
      </label>
      <div className="relative">
        <input
          id={id}
          type="number"
          value={Number.isFinite(value) ? value : ''}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(event) => onChange(Number(event.target.value))}
          className="w-full rounded-lg border border-forest-600 bg-forest-800 px-3 py-2 text-sm text-mist-100 transition-colors hover:border-emerald-500/50 focus-visible:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
        />
        {unit && (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-xs text-mist-500">
            {unit}
          </span>
        )}
      </div>
    </div>
  )
}

export function QuantumTextInput({
  label,
  hint,
  disabled = false,
  value,
  onChange,
}: BaseProps & {
  value: string
  onChange: (value: string) => void
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        <span>{label}</span>
        {hint && <span className="text-[11px] font-normal text-mist-600">{hint}</span>}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-forest-600 bg-forest-800 px-3 py-2 font-mono text-sm text-mist-100 transition-colors hover:border-emerald-500/50 focus-visible:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
      />
    </div>
  )
}

export function QuantumToggle({
  label,
  hint,
  disabled = false,
  checked,
  onChange,
}: BaseProps & {
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  const id = useId()
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-forest-600 bg-forest-800/60 hover:border-emerald-500/40'
      }`}
    >
      <span>
        <span className="flex items-center gap-2 text-sm text-mist-100">{label}</span>
        {hint && <span className="mt-0.5 block text-[11px] text-mist-600">{hint}</span>}
      </span>
      <span
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? 'bg-emerald-500' : 'bg-forest-600'
        }`}
      >
        <span
          className={`absolute top-0.5 size-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-[18px]' : 'translate-x-0.5'
          }`}
        />
      </span>
    </button>
  )
}