import React from 'react';
import { Radio, Droplets, CloudRain, ShieldAlert } from 'lucide-react';
import RiskBadge from './RiskBadge';

const DashboardCards = ({ summary }) => {
  const totalSensors = summary?.total_sensors || 0;
  const latestWaterLevel = summary?.latest_water_level !== undefined ? summary.latest_water_level.toFixed(2) : '0.00';
  const totalRainfall = summary?.total_rainfall !== undefined ? summary.total_rainfall.toFixed(1) : '0.0';
  const highestRiskLevel = summary?.highest_risk_level || 'LOW';

  const cards = [
    {
      title: 'Total Sensors',
      value: totalSensors,
      unit: 'active nodes',
      icon: Radio,
      iconBg: 'bg-blue-950/80 text-blue-400 border-blue-800/50',
      borderAccent: 'border-blue-900/40',
      description: 'Registered telemetry sensors'
    },
    {
      title: 'Latest Water Level',
      value: `${latestWaterLevel}`,
      unit: 'meters (m)',
      icon: Droplets,
      iconBg: 'bg-cyan-950/80 text-cyan-400 border-cyan-800/50',
      borderAccent: 'border-cyan-900/40',
      description: 'Peak real-time reading'
    },
    {
      title: 'Cumulative Rainfall',
      value: `${totalRainfall}`,
      unit: 'mm',
      icon: CloudRain,
      iconBg: 'bg-indigo-950/80 text-indigo-400 border-indigo-800/50',
      borderAccent: 'border-indigo-900/40',
      description: 'Total current precipitation'
    },
    {
      title: 'Current Risk Level',
      value: <RiskBadge riskLevel={highestRiskLevel} showPulse={highestRiskLevel === 'CRITICAL'} />,
      unit: 'Severity status',
      icon: ShieldAlert,
      iconBg: 'bg-rose-950/80 text-rose-400 border-rose-800/50',
      borderAccent: highestRiskLevel === 'CRITICAL' ? 'border-rose-600/80 shadow-lg shadow-rose-950/30' : 'border-slate-800',
      isCustomValue: true,
      description: 'Max calculated risk tier'
    }
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {cards.map((card, idx) => {
        const Icon = card.icon;
        return (
          <div 
            key={idx}
            className={`bg-slate-900/80 border ${card.borderAccent} rounded-xl p-5 backdrop-blur-sm transition-all duration-200 hover:border-slate-700/80 flex flex-col justify-between`}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">{card.title}</p>
                <div className="mt-2 flex items-baseline gap-2">
                  {card.isCustomValue ? (
                    <div className="py-1">{card.value}</div>
                  ) : (
                    <>
                      <span className="text-3xl font-extrabold text-white tracking-tight font-mono">{card.value}</span>
                      <span className="text-xs text-slate-400 font-sans">{card.unit}</span>
                    </>
                  )}
                </div>
              </div>
              <div className={`p-2.5 rounded-xl border ${card.iconBg}`}>
                <Icon className="h-5 w-5" />
              </div>
            </div>
            <p className="text-[11px] text-slate-500 mt-4 border-t border-slate-800/60 pt-2">
              {card.description}
            </p>
          </div>
        );
      })}
    </div>
  );
};

export default DashboardCards;
