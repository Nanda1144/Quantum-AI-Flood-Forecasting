import type { HTMLAttributes, ReactNode } from 'react'

interface GlassCardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  glow?: boolean
  padded?: boolean
}

export function GlassCard({ children, glow = false, padded = true, className = '', ...rest }: GlassCardProps) {
  const padding = padded ? 'p-5' : ''
  return (
    <section
      {...rest}
      className={`glass-card ${glow ? 'glass-card--glow' : ''} ${padding} ${className}`}
    >
      {children}
    </section>
  )
}