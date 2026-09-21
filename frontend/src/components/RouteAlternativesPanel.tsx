'use client';

import React, { useCallback, useEffect, useState } from 'react';
import ProvenanceBadge from './ProvenanceBadge';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface RouteLegKPI {
  sequence: number;
  mode: string;
  from_locode: string;
  to_locode: string;
  from_node_id: number;
  to_node_id: number;
  departure_at: string;
  arrival_at: string;
  transit_h: number;
  cost_usd: number;
  co2_kg: number;
  reliability: number;
  provenance: string;
}

export interface RoutePlanResult {
  plan_id: number | null;
  rank: number;
  recommended: boolean;
  rationale: string;
  priority: string;
  plan_type: string;
  total_cost_usd: number;
  total_time_h: number;
  total_co2_kg: number;
  reliability_score: number;
  risk_index: number;
  score: number;
  provenance: string;
  legs: RouteLegKPI[];
}

export interface RouteAlternativesPanelProps {
  shipmentId: string | null;
  /** Refresh key — increment to re-fetch */
  refreshKey?: number;
  /** Whether to show the plan-type filter tabs */
  showTabs?: boolean;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const MODE_ICON: Record<string, string> = {
  ROAD: '🚛',
  RAIL: '🚂',
  SEA: '🚢',
  AIR: '✈️',
};

const MODE_COLOR: Record<string, string> = {
  ROAD: '#FDBA74',
  RAIL: '#6EE7B7',
  SEA: '#7DD3FC',
  AIR: '#C4B5FD',
};

const PRIORITY_COLOR: Record<string, string> = {
  CRITICAL: '#FCA5A5',
  EXPRESS: '#FDBA74',
  STANDARD: '#7DD3FC',
  ECONOMY: '#6EE7B7',
};

function fmtUsd(n: number): string {
  return `$${Math.round(n).toLocaleString()}`;
}

function fmtH(h: number): string {
  const d = Math.floor(h / 24);
  const r = Math.round(h % 24);
  return d > 0 ? `${d}d ${r}h` : `${r}h`;
}

function fmtCO2(kg: number): string {
  return kg >= 1000 ? `${(kg / 1000).toFixed(1)} t` : `${Math.round(kg)} kg`;
}

function fmtPct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function ScoreBadge({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? '#34D399' : pct >= 60 ? '#FDE68A' : '#FCA5A5';
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 3,
        fontSize: 10,
        fontWeight: 700,
        padding: '2px 6px',
        borderRadius: 4,
        background: `${color}20`,
        color,
        border: `1px solid ${color}40`,
      }}
    >
      {pct}
      <span style={{ fontWeight: 400, opacity: 0.8 }}>score</span>
    </span>
  );
}

function LegTimeline({ legs }: { legs: RouteLegKPI[] }) {
  if (!legs.length) return null;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        flexWrap: 'wrap',
        rowGap: 4,
        marginTop: 4,
      }}
    >
      {legs.map((leg, i) => (
        <React.Fragment key={i}>
          {i === 0 && (
            <span
              style={{
                fontSize: 9,
                color: '#94A3B8',
                marginRight: 3,
                whiteSpace: 'nowrap',
              }}
            >
              {leg.from_locode || `N${leg.from_node_id}`}
            </span>
          )}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              background: `${MODE_COLOR[leg.mode] ?? '#64748B'}22`,
              border: `1px solid ${MODE_COLOR[leg.mode] ?? '#64748B'}55`,
              borderRadius: 4,
              padding: '1px 5px',
            }}
            title={`${leg.mode}: ${leg.from_locode || leg.from_node_id} → ${leg.to_locode || leg.to_node_id} · ${fmtH(leg.transit_h)} · ${fmtUsd(leg.cost_usd)} · CO₂ ${fmtCO2(leg.co2_kg)}`}
          >
            <span style={{ fontSize: 10 }}>{MODE_ICON[leg.mode] ?? '📦'}</span>
            <span
              style={{
                fontSize: 8,
                fontWeight: 700,
                color: MODE_COLOR[leg.mode] ?? '#CBD5E1',
              }}
            >
              {leg.mode}
            </span>
            <span style={{ fontSize: 8, color: '#94A3B8' }}>{fmtH(leg.transit_h)}</span>
          </div>
          <span
            style={{
              fontSize: 9,
              color: '#94A3B8',
              marginLeft: 3,
              whiteSpace: 'nowrap',
            }}
          >
            {leg.to_locode || `N${leg.to_node_id}`}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
}

function PlanCard({
  plan,
  expanded,
  onToggle,
}: {
  plan: RoutePlanResult;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <article
      style={{
        border: plan.recommended
          ? '1px solid rgba(52,211,153,0.5)'
          : '1px solid rgba(148,163,184,0.2)',
        borderRadius: 8,
        padding: '8px 10px',
        background: plan.recommended
          ? 'rgba(16,185,129,0.06)'
          : 'rgba(15,23,42,0.45)',
        cursor: 'pointer',
        transition: 'border-color 0.15s ease',
      }}
      onClick={onToggle}
    >
      {/* ── Card header ── */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 700, color: '#E2E8F0', minWidth: 48 }}>
          #{plan.rank}
          {plan.recommended && (
            <span
              style={{
                marginLeft: 5,
                fontSize: 8,
                fontWeight: 800,
                padding: '1px 5px',
                borderRadius: 3,
                background: 'rgba(52,211,153,0.25)',
                color: '#34D399',
              }}
            >
              REC
            </span>
          )}
        </span>

        {/* Mode chain */}
        <LegTimeline legs={plan.legs} />

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <ScoreBadge score={plan.score} />
          <span
            style={{
              fontSize: 9,
              padding: '1px 5px',
              borderRadius: 3,
              background: `${PRIORITY_COLOR[plan.priority] ?? '#94A3B8'}18`,
              color: PRIORITY_COLOR[plan.priority] ?? '#94A3B8',
              border: `1px solid ${PRIORITY_COLOR[plan.priority] ?? '#94A3B8'}40`,
              fontWeight: 600,
            }}
          >
            {plan.priority}
          </span>
        </div>
      </header>

      {/* ── KPI bar ── */}
      <dl
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '2px 6px',
          fontSize: 10,
          margin: '6px 0 0',
          padding: 0,
        }}
      >
        {[
          { label: 'Cost', value: fmtUsd(plan.total_cost_usd), color: '#FDE68A' },
          { label: 'Transit', value: fmtH(plan.total_time_h), color: '#7DD3FC' },
          { label: 'CO₂', value: fmtCO2(plan.total_co2_kg), color: '#6EE7B7' },
          { label: 'Reliability', value: fmtPct(plan.reliability_score), color: '#C4B5FD' },
        ].map(({ label, value, color }) => (
          <React.Fragment key={label}>
            <dt style={{ color: '#64748B' }}>{label}</dt>
            <dd style={{ margin: 0, color, fontWeight: 700 }}>{value}</dd>
          </React.Fragment>
        ))}
      </dl>

      {/* ── Expanded rationale + leg table ── */}
      {expanded && (
        <div style={{ marginTop: 8 }}>
          <p
            style={{
              fontSize: 10,
              color: '#94A3B8',
              margin: '0 0 6px',
              lineHeight: 1.5,
            }}
          >
            {plan.rationale}
          </p>

          {/* Leg detail table */}
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 9,
            }}
          >
            <thead>
              <tr style={{ color: '#64748B', borderBottom: '1px solid rgba(148,163,184,0.15)' }}>
                {['#', 'Mode', 'From', 'To', 'Depart', 'Arrive', 'h', 'Cost', 'CO₂', 'P(ok)', 'Prov'].map(
                  (h) => (
                    <th key={h} style={{ textAlign: 'left', padding: '2px 4px', fontWeight: 500 }}>
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {plan.legs.map((leg) => (
                <tr
                  key={leg.sequence}
                  style={{ borderBottom: '1px solid rgba(148,163,184,0.08)', color: '#CBD5E1' }}
                >
                  <td style={{ padding: '2px 4px' }}>{leg.sequence}</td>
                  <td style={{ padding: '2px 4px' }}>
                    <span style={{ color: MODE_COLOR[leg.mode] ?? '#E2E8F0' }}>
                      {MODE_ICON[leg.mode] ?? ''} {leg.mode}
                    </span>
                  </td>
                  <td style={{ padding: '2px 4px', color: '#94A3B8' }}>
                    {leg.from_locode || `N${leg.from_node_id}`}
                  </td>
                  <td style={{ padding: '2px 4px', color: '#94A3B8' }}>
                    {leg.to_locode || `N${leg.to_node_id}`}
                  </td>
                  <td style={{ padding: '2px 4px' }}>
                    {new Date(leg.departure_at).toLocaleString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td style={{ padding: '2px 4px' }}>
                    {new Date(leg.arrival_at).toLocaleString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td style={{ padding: '2px 4px', color: '#7DD3FC' }}>{fmtH(leg.transit_h)}</td>
                  <td style={{ padding: '2px 4px', color: '#FDE68A' }}>{fmtUsd(leg.cost_usd)}</td>
                  <td style={{ padding: '2px 4px', color: '#6EE7B7' }}>{fmtCO2(leg.co2_kg)}</td>
                  <td style={{ padding: '2px 4px', color: '#C4B5FD' }}>
                    {fmtPct(leg.reliability)}
                  </td>
                  <td style={{ padding: '2px 4px' }}>
                    <ProvenanceBadge
                      provenance={leg.provenance as 'SIMULATED' | 'DERIVED' | 'LIVE' | 'REPLAY' | 'POLICY'}
                      size="xs"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function RouteAlternativesPanel({
  shipmentId,
  refreshKey = 0,
  showTabs = false,
}: RouteAlternativesPanelProps) {
  const [plans, setPlans] = useState<RoutePlanResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRank, setExpandedRank] = useState<number | null>(1);
  const [planTypeFilter, setPlanTypeFilter] = useState<string>('');

  const fetch = useCallback(
    async (id: string) => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ shipment_id: id });
        if (planTypeFilter) params.set('plan_type', planTypeFilter);
        const resp = await window.fetch(`/api/v1/plan?${params.toString()}`, {
          credentials: 'include',
        });
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(`${resp.status}: ${text}`);
        }
        const data = await resp.json();
        setPlans((data as { routes: RoutePlanResult[] }).routes ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [planTypeFilter],
  );

  useEffect(() => {
    if (!shipmentId) {
      setPlans([]);
      return;
    }
    void fetch(shipmentId);
  }, [shipmentId, refreshKey, fetch]);

  if (!shipmentId) return null;

  return (
    <section aria-label="Route alternatives" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          justifyContent: 'space-between',
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 700, color: '#E2E8F0' }}>Route Alternatives</span>
        <ProvenanceBadge provenance="DERIVED" size="xs" title="Planner KPIs: DERIVED (computed) or SIMULATED (seeded schedules)" />
      </div>

      {/* Tabs */}
      {showTabs && (
        <div style={{ display: 'flex', gap: 4 }}>
          {['', 'INITIAL', 'ALTERNATIVE', 'RECOVERY'].map((pt) => (
            <button
              key={pt || 'ALL'}
              onClick={() => setPlanTypeFilter(pt)}
              style={{
                fontSize: 9,
                fontWeight: planTypeFilter === pt ? 700 : 400,
                padding: '2px 8px',
                borderRadius: 4,
                background: planTypeFilter === pt ? 'rgba(99,102,241,0.3)' : 'transparent',
                border: '1px solid rgba(148,163,184,0.2)',
                color: planTypeFilter === pt ? '#A5B4FC' : '#64748B',
                cursor: 'pointer',
              }}
            >
              {pt || 'ALL'}
            </button>
          ))}
        </div>
      )}

      {/* States */}
      {loading && (
        <div
          style={{
            fontSize: 11,
            color: '#94A3B8',
            padding: '8px 0',
            animation: 'pulse 1.5s ease infinite',
          }}
        >
          Computing route alternatives…
        </div>
      )}

      {error && !loading && (
        <div role="alert" style={{ fontSize: 11, color: '#FCA5A5' }}>
          {error}
        </div>
      )}

      {!loading && !error && plans.length === 0 && (
        <div style={{ fontSize: 11, color: '#64748B', padding: '8px 0' }}>
          No route plans available for this shipment. Use the plan endpoint to generate alternatives.
        </div>
      )}

      {/* Plan cards */}
      {plans.map((plan) => (
        <PlanCard
          key={`${plan.plan_id ?? plan.rank}-${plan.plan_type}`}
          plan={plan}
          expanded={expandedRank === plan.rank}
          onToggle={() => setExpandedRank((prev) => (prev === plan.rank ? null : plan.rank))}
        />
      ))}
    </section>
  );
}
