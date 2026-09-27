import type { RoutePlanResult } from '@/components/RouteAlternativesPanel';

export function mapPlanType(tab: string): string | undefined {
  return tab || undefined;
}

export function mapPlanResponse(response: { routes: RoutePlanResult[] }): RoutePlanResult[] {
  return response.routes || [];
}

export function mapPlanError(status: number, defaultMessage: string): string {
  if (status === 401 || status === 403) {
    return 'Reroute planning requires an operator role (sign in as operator or admin)';
  }
  return defaultMessage;
}
