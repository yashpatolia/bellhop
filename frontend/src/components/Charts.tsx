import type { CSSProperties } from 'react'

export function Bars({ values, labels, highlight, height = 96 }: { values: number[]; labels?: string[]; highlight?: number; height?: number }) {
  const max = Math.max(1, ...values)
  return (
    <div className="bars" style={{ height }} role="img" aria-label={`Bar chart, latest value ${values[values.length - 1]}`}>
      {values.map((v, i) => (
        <div key={i} className="bar-col">
          <div className="bar-val">{v || ''}</div>
          <div className={`bar ${i === highlight ? 'hl' : ''}`} style={{ height: `${Math.max(4, (v / max) * 100)}%`, animationDelay: `${i * 30}ms` }} />
          {labels && <div className="bar-lab">{labels[i]}</div>}
        </div>
      ))}
    </div>
  )
}

export function HBars({ rows, unit = '' }: { rows: { label: string; value: number }[]; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <div className="hbars">
      {rows.map((r, i) => (
        <div key={r.label} className="hbar">
          <span className="hbar-label">{r.label}</span>
          <span className="hbar-track">
            <span className="hbar-fill" style={{ width: `${(r.value / max) * 100}%`, animationDelay: `${i * 50}ms` }} />
          </span>
          <span className="hbar-val">
            {r.value}
            {unit}
          </span>
        </div>
      ))}
    </div>
  )
}

export function Sparkline({ values, min, max, color = 'var(--accent)', w = 120, h = 34 }: { values: number[]; min: number; max: number; color?: string; w?: number; h?: number }) {
  if (values.length < 2) return <span className="spark-none">Not enough readings yet</span>
  const step = w / (values.length - 1)
  const y = (v: number) => h - 4 - ((v - min) / (max - min)) * (h - 8)
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = values[values.length - 1]
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label={`Trend, latest ${last}`}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={(values.length - 1) * step} cy={y(last)} r="3.2" fill={color} />
    </svg>
  )
}

export function Ring({ value, target, label, sub }: { value: number; target: number; label: string; sub: string }) {
  const r = 46
  const c = 2 * Math.PI * r
  const ok = value >= target
  return (
    <div className="ring">
      <svg viewBox="0 0 120 120" width="120" height="120" role="img" aria-label={`${label} ${Math.round(value * 100)} percent, target ${target * 100} percent`}>
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--line)" strokeWidth="10" />
        <circle
          cx="60"
          cy="60"
          r={r}
          fill="none"
          stroke={ok ? 'var(--u1)' : 'var(--u3)'}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${c * Math.min(1, value)} ${c}`}
          transform="rotate(-90 60 60)"
          style={{ transition: 'stroke-dasharray 0.8s ease' }}
        />
        <line x1="60" y1="4" x2="60" y2="16" stroke="var(--ink-3)" strokeWidth="2" transform={`rotate(${target * 360} 60 60)`} />
        <text x="60" y="66" textAnchor="middle" className="ring-num">
          {Math.round(value * 100)}%
        </text>
      </svg>
      <div>
        <div className="ring-label">{label}</div>
        <div className="ring-sub">{sub}</div>
      </div>
    </div>
  )
}

export function Stars({ value, size = 16 }: { value: number; size?: number }) {
  const style: CSSProperties = { fontSize: size }
  return (
    <span className="stars" style={style} role="img" aria-label={`${value.toFixed(1)} out of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={n <= Math.round(value) ? 'on' : ''}>
          ★
        </span>
      ))}
    </span>
  )
}
