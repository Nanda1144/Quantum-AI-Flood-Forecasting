/**
 * Fixed, page-wide backdrop for the Quantum Optimization command center.
 * Three subtle layers, all pointer-events-none and behind content (z-index:-1):
 *  - a slowly panning circuit lattice grid,
 *  - two blurred glow orbs (emerald + cyan),
 *  - a pair of SVG circuit traces with pulses flowing along them.
 */

export function QuantumCircuitBackground() {
  return (
    <>
      <div aria-hidden="true" className="quantum-circuit-grid" />
      <div aria-hidden="true" className="quantum-orb quantum-orb--emerald" />
      <div aria-hidden="true" className="quantum-orb quantum-orb--cyan" />

      <svg
        aria-hidden="true"
        className="pointer-events-none fixed -bottom-10 -right-16 z-[-1] h-[420px] w-[640px] opacity-50"
        viewBox="0 0 640 420"
        fill="none"
      >
        <polyline
          className="quantum-trace"
          stroke="#10b981"
          strokeOpacity="0.5"
          strokeWidth="1.2"
          points="0,340 90,340 110,290 170,290 170,220 240,220 240,150 310,150 310,210 380,210 380,280 460,280 490,330 640,330"
        />
        <circle className="quantum-node" cx="310" cy="150" r="4" fill="#34d399" />
        <circle className="quantum-node" cx="170" cy="290" r="3.5" fill="#10b981" />

        <polyline
          className="quantum-trace quantum-trace--fast"
          stroke="#22d3ee"
          strokeOpacity="0.45"
          strokeWidth="1.1"
          points="0,120 70,120 90,200 170,200 170,120 260,120 260,40 360,40 360,100 470,100 470,160 560,160 640,160"
        />
        <circle className="quantum-node" cx="260" cy="120" r="3.5" fill="#22d3ee" />
        <circle className="quantum-node" cx="470" cy="100" r="4" fill="#67e8f9" />

        <circle className="quantum-node" cx="560" cy="160" r="2.5" fill="#22d3ee" />
        <circle cx="640" cy="330" r="6" fill="none" stroke="#10b981" strokeOpacity="0.6" strokeWidth="1">
          <animate attributeName="r" values="3;7;3" dur="3.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.9;0.15;0.9" dur="3.2s" repeatCount="indefinite" />
        </circle>
        <circle cx="0" cy="120" r="6" fill="none" stroke="#22d3ee" strokeOpacity="0.6" strokeWidth="1">
          <animate attributeName="r" values="3;7;3" dur="3.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.9;0.15;0.9" dur="3.2s" repeatCount="indefinite" />
        </circle>
      </svg>
    </>
  )
}