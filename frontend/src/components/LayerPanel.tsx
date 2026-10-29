'use client';

import { memo, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Ship, Anchor, AlertTriangle, CloudLightning,
  Plane, Sun, Activity, X, Filter
} from 'lucide-react';

interface LayerPanelProps {
  data: any;
  activeLayers: Record<string, boolean>;
  setActiveLayers: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  isMobile?: boolean;
  theme?: 'core' | 'ghost';
  setTheme?: (theme: 'core' | 'ghost') => void;
  capabilities?: Record<string, boolean>;
  onClose?: () => void;
}

interface LayerItem {
  key: string;
  label: string;
  description: string;
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  count?: number;
}

interface LayerCategory {
  title: string;
  items: LayerItem[];
}

function ToggleSwitch({ active }: { active: boolean }) {
  return (
    <span
      role="presentation"
      className="relative flex-shrink-0 block cursor-pointer"
      style={{ width: 32, height: 18 }}
    >
      <div
        className="absolute inset-0 rounded-full transition-all duration-200"
        style={{
          background: active ? 'var(--cobalt)' : 'var(--paper-contrast, #EAEBE6)',
          border: active ? '1px solid var(--cobalt)' : '1px solid var(--border-hairline)',
        }}
      />
      <motion.div
        className="absolute top-[2px] rounded-full"
        style={{
          width: 12,
          height: 12,
          background: active ? '#FFFFFF' : 'var(--text-secondary)',
        }}
        animate={{ left: active ? 16 : 2 }}
        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      />
    </span>
  );
}

function LayerPanel({
  data,
  activeLayers,
  setActiveLayers,
  isMobile,
  onClose,
}: LayerPanelProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onClose) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const toggle = (key: string) => {
    setActiveLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const getEntityCount = (key: string): number | undefined => {
    if (!data) return undefined;
    switch (key) {
      case 'maritime':
        return data.maritime_ships?.length ?? (data.maritime_ports?.length ? data.maritime_ports.length : undefined);
      case 'ports':
        return data.maritime_ports?.length ?? 578;
      case 'active_ports_only':
        return 16;
      case 'routes':
        return 12;
      case 'disruptions':
        return 4;
      case 'weather':
        return data.weather_events?.length ?? 0;
      case 'flights':
        return data.commercial_flights?.length ?? 0;
      default:
        return undefined;
    }
  };

  const categories: LayerCategory[] = [
    {
      title: 'FLEET & MARITIME',
      items: [
        {
          key: 'maritime',
          label: 'Active Vessels & AIS',
          description: 'Live cargo container ships and tankers',
          icon: Ship,
          count: getEntityCount('maritime'),
        },
        {
          key: 'routes',
          label: 'Multimodal Corridors',
          description: 'Global ocean lanes, rail & highway networks',
          icon: Activity,
          count: getEntityCount('routes'),
        },
        {
          key: 'ports',
          label: 'Global Ports',
          description: 'All 578 UN/LOCODE container hubs',
          icon: Anchor,
          count: getEntityCount('ports'),
        },
        {
          key: 'active_ports_only',
          label: 'In-Transit Ports Only',
          description: 'Focus on active origins, destinations & chokepoints',
          icon: Filter,
        },
      ],
    },
    {
      title: 'DISRUPTIONS & RISK TELEMETRY',
      items: [
        {
          key: 'disruptions',
          label: 'Disruption Sonar Rings',
          description: 'Red Sea, Suez, Malacca & chokepoint alerts',
          icon: AlertTriangle,
          count: getEntityCount('disruptions'),
        },
        {
          key: 'weather',
          label: 'Marine Weather & Cyclones',
          description: 'Severe gale force, typhoon & storm cells',
          icon: CloudLightning,
          count: getEntityCount('weather'),
        },
      ],
    },
    {
      title: 'AUXILIARY & MULTIMODAL',
      items: [
        {
          key: 'flights',
          label: 'Air Freight Corridors',
          description: 'Scheduled cargo aircraft & hub links',
          icon: Plane,
          count: getEntityCount('flights'),
        },
        {
          key: 'day_night',
          label: 'Solar Terminator',
          description: 'Global daylight & nighttime boundary',
          icon: Sun,
        },
      ],
    },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: -8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
      className={`w-80 max-w-[calc(100vw-32px)] flex flex-col pointer-events-auto select-none rounded-[3px] border ${
        isMobile ? 'p-3' : 'p-3.5'
      }`}
      style={{
        backgroundColor: 'var(--paper)',
        borderColor: 'var(--border-hairline)',
        boxShadow: 'none',
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[var(--border-hairline)]">
        <div>
          <span className="text-[11px] font-bold font-mono tracking-[0.16em] uppercase text-[var(--ink)]">
            MAP TELEMETRY LAYERS
          </span>
          <p className="text-[10px] text-[var(--text-secondary)] font-mono">
            Control Tower Visualization Feed
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded text-[var(--text-secondary)] hover:text-[var(--ink)] hover:bg-[var(--paper-contrast)] transition-colors cursor-pointer"
            aria-label="Close layers"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* Layer Groups */}
      <div className="flex flex-col gap-3.5 max-h-[70vh] overflow-y-auto pr-1">
        {categories.map((category) => (
          <div key={category.title} className="flex flex-col gap-1.5">
            <span className="text-[9px] font-mono tracking-[0.2em] font-semibold text-[var(--text-secondary)] uppercase">
              {category.title}
            </span>

            <div className="flex flex-col gap-1">
              {category.items.map((item) => {
                const isActive = !!activeLayers[item.key];
                const Icon = item.icon;

                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => toggle(item.key)}
                    className="w-full flex items-center justify-between p-2 rounded-[2px] border text-left transition-colors cursor-pointer group"
                    style={{
                      backgroundColor: isActive ? 'rgba(37, 71, 200, 0.04)' : 'transparent',
                      borderColor: isActive ? 'var(--cobalt)' : 'var(--border-hairline)',
                    }}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 pr-2">
                      {Icon && (
                        <Icon
                          className="w-4 h-4 flex-shrink-0 transition-colors"
                          style={{
                            color: isActive ? 'var(--cobalt)' : 'var(--text-secondary)',
                          }}
                        />
                      )}
                      <div className="flex flex-col min-w-0">
                        <span
                          className="text-[11px] font-semibold tracking-wide truncate"
                          style={{
                            fontFamily: 'var(--font-ui)',
                            color: isActive ? 'var(--ink)' : 'var(--text-secondary)',
                          }}
                        >
                          {item.label}
                        </span>
                        <span className="text-[9px] text-[var(--text-secondary)] font-mono truncate">
                          {item.description}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      {item.count !== undefined && (
                        <span
                          className="text-[9px] font-mono tabular-nums px-1.5 py-0.5 rounded-[2px] border"
                          style={{
                            backgroundColor: isActive ? 'rgba(37, 71, 200, 0.08)' : 'var(--paper)',
                            borderColor: isActive ? 'var(--cobalt)' : 'var(--border-hairline)',
                            color: isActive ? 'var(--cobalt)' : 'var(--text-secondary)',
                          }}
                        >
                          {item.count}
                        </span>
                      )}
                      <ToggleSwitch active={isActive} />
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Footer shortcut helper */}
      <div className="mt-3 pt-2 border-t border-[var(--border-hairline)] flex items-center justify-between text-[10px] font-mono text-[var(--text-secondary)]">
        <span>Press <kbd className="px-1 py-0.2 rounded border border-[var(--border-hairline)] bg-[var(--paper)] text-[var(--ink)]">L</kbd> to toggle</span>
        <button
          onClick={() => {
            setActiveLayers({
              maritime: true,
              routes: true,
              ports: true,
              disruptions: true,
              weather: false,
              flights: false,
              day_night: false,
            });
          }}
          className="text-[9px] hover:text-[var(--cobalt)] underline cursor-pointer"
        >
          RESET DEFAULT
        </button>
      </div>
    </motion.div>
  );
}

export default memo(LayerPanel);
