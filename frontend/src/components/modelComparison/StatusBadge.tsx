import type { RegistryStatus } from '../../types/ai'

const styles: Record<RegistryStatus, string> = {
  active: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  retired: 'border-mist-600/40 bg-forest-700/50 text-mist-400',
  development: 'border-ai-500/40 bg-ai-500/10 text-ai-300',
}

export function StatusBadge({ status }: { status: RegistryStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${styles[status]}`}
    >
      {status}
    </span>
  )
}