import { describe, it, expect } from 'vitest';
import { mapPlanType, mapPlanResponse, mapPlanError } from './alternatives';
import type { RoutePlanResult } from '@/components/RouteAlternativesPanel';

describe('alternatives', () => {
  it('tab mapping: ALL -> omitted, others -> as-is', () => {
    expect(mapPlanType('')).toBeUndefined();
    expect(mapPlanType('INITIAL')).toBe('INITIAL');
    expect(mapPlanType('ALTERNATIVE')).toBe('ALTERNATIVE');
    expect(mapPlanType('RECOVERY')).toBe('RECOVERY');
  });

  it('401/403 -> friendly message mapping', () => {
    expect(mapPlanError(401, 'Default error')).toBe('Reroute planning requires an operator role (sign in as operator or admin)');
    expect(mapPlanError(403, 'Default error')).toBe('Reroute planning requires an operator role (sign in as operator or admin)');
    expect(mapPlanError(500, 'Server error')).toBe('Server error');
  });

  it('empty routes -> empty state, not an error', () => {
    expect(mapPlanResponse({ routes: [] })).toEqual([]);
  });

  it('rows mapping from a fixture PlanResponse', () => {
    const fixture: RoutePlanResult = {
      plan_id: 1,
      rank: 1,
      recommended: true,
      rationale: 'Best option',
      priority: 'CRITICAL',
      plan_type: 'ALTERNATIVE',
      total_cost_usd: 1000,
      total_time_h: 24,
      total_co2_kg: 500,
      reliability_score: 0.95,
      risk_index: 0.1,
      score: 0.9,
      provenance: 'DERIVED',
      legs: [
        {
          sequence: 1,
          mode: 'SEA',
          from_locode: 'USNYC',
          to_locode: 'GBFEL',
          from_node_id: 1,
          to_node_id: 2,
          departure_at: '2026-10-01T00:00:00Z',
          arrival_at: '2026-10-10T00:00:00Z',
          transit_h: 216,
          cost_usd: 1000,
          co2_kg: 500,
          reliability: 0.95,
          provenance: 'DERIVED',
        }
      ]
    };
    
    const res = mapPlanResponse({ routes: [fixture] });
    expect(res).toHaveLength(1);
    expect(res[0].recommended).toBe(true);
    expect(res[0].legs[0].mode).toBe('SEA');
  });
});
