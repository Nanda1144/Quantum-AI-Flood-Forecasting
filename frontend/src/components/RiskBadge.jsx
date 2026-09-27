import React from 'react';

const RiskBadge = ({ riskLevel, showPulse = false }) => {
  const level = (riskLevel || 'LOW').toUpperCase();

  const config = {
    LOW: {
      bg: 'bg-emerald-950/80 text-emerald-400 border-emerald-800/60',
      dot: 'bg-emerald-400',
      text: 'LOW'
    },
    MEDIUM: {
      bg: 'bg-amber-950/80 text-amber-400 border-amber-800/60',
      dot: 'bg-amber-400',
      text: 'MEDIUM'
    },
    HIGH: {
      bg: 'bg-orange-950/80 text-orange-400 border-orange-800/60',
      dot: 'bg-orange-400',
      text: 'HIGH'
    },
    CRITICAL: {
      bg: 'bg-rose-950/90 text-rose-300 border-rose-700/80 shadow-lg shadow-rose-950/50',
      dot: 'bg-rose-500 animate-ping',
      text: 'CRITICAL'
    }
  };

  const current = config[level] || config.LOW;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${current.bg} transition-all duration-300`}>
      <span className={`h-2 w-2 rounded-full ${current.dot}`} />
      <span>{current.text}</span>
    </span>
  );
};

export default RiskBadge;
