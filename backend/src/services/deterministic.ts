/** Deterministic PRNG helpers shared by the optimization pipeline. */

export type Rng = () => number

export function mulberry32(seed: number): Rng {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Stable integer hash so identical inputs always reproduce identical output. */
export function hashString(value: string): number {
  let h = 2166136261
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Hash a seed-less string into a deterministic numeric seed. */
export function seedFrom(values: unknown[]): number {
  let acc = 2166136261
  for (const value of values) {
    const chunk = typeof value === 'string' ? value : JSON.stringify(value)
    for (let i = 0; i < chunk.length; i++) {
      acc ^= chunk.charCodeAt(i)
      acc = Math.imul(acc, 16777619)
    }
  }
  return acc >>> 0
}