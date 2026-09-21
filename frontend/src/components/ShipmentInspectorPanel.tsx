"use client";

import { useCallback, useEffect, useState } from "react";
import {
  askCopilot as askCopilotApi,
  getAlerts,
  getShipmentFinancials,
  getShipmentPrediction,
  nexaClient,
  NexaHttpError,
  type Alert,
  type CopilotAskResponse,
  type ShipmentDetail,
  type ShipmentFinancialsResponse,
  type ShipmentPredictResponse,
} from "@/lib/nexafreight";
import ProvenanceBadge from "./ProvenanceBadge";
import RouteAlternativesPanel from "./RouteAlternativesPanel";


interface ShipmentInspectorPanelProps {
  shipmentId: string | null;
  onClose: () => void;
  /** bump to force a reload of every panel block (e.g. after a decision) */
  refreshKey?: number;
  /** the signed-in user's role letter — financials hidden for VIEWER */
  viewerRole?: string;
}

const fmtUsd = (n: number | null | undefined) =>
  n == null
    ? "—"
    : `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

/** Severity → accent color */
const sevColor: Record<string, string> = {
  CRITICAL: "#FCA5A5",
  HIGH: "#FDBA74",
  MEDIUM: "#FDE68A",
  LOW: "#CBD5E1",
};

const COPILOT_PLACEHOLDER =
  "Why was this shipment rerouted? · Are we on time for SLA? · What is the demurrage on this shipment?";

export default function ShipmentInspectorPanel({
  shipmentId,
  onClose,
  refreshKey = 0,
  viewerRole = "VIEWER",
}: ShipmentInspectorPanelProps) {
  const [shipment, setShipment] = useState<ShipmentDetail | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [prediction, setPrediction] = useState<ShipmentPredictResponse | null>(null);
  const [financials, setFinancials] = useState<ShipmentFinancialsResponse | null>(null);
  const [financialsDenied, setFinancialsDenied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [copilotQuestion, setCopilotQuestion] = useState("");
  const [copilotAnswer, setCopilotAnswer] = useState<CopilotAskResponse | null>(null);
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotError, setCopilotError] = useState<string | null>(null);

  const canSeeFinancials = viewerRole === "ADMIN" || viewerRole === "OPERATOR";

  useEffect(() => {
    if (!shipmentId) {
      setShipment(null);
      setAlerts([]);
      setPrediction(null);
      setFinancials(null);
      setCopilotAnswer(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    nexaClient
      .getShipmentDetail(shipmentId)
      .then((data) => {
        if (!cancelled) setShipment(data as ShipmentDetail);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message ?? "Failed to load shipment");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    // Alerts for this shipment (queue-wide list, filtered client-side)
    getAlerts()
      .then((data) => {
        if (!cancelled) setAlerts(data.alerts.filter((a) => a.shipment_id === shipmentId));
      })
      .catch(() => undefined);

    // ML delay prediction — null when the registry is offline
    getShipmentPrediction(shipmentId)
      .then((p) => {
        if (!cancelled) setPrediction(p);
      })
      .catch(() => undefined);

    // Financials — gated to non-VIEWER roles; 403 hides the section quietly
    if (canSeeFinancials) {
      setFinancialsDenied(false);
      getShipmentFinancials(shipmentId)
        .then((f) => {
          if (!cancelled) setFinancials(f);
        })
        .catch((err) => {
          if (!cancelled && err instanceof NexaHttpError && err.status === 403) {
            setFinancialsDenied(true);
          }
        });
    }

    return () => {
      cancelled = true;
    };
  }, [shipmentId, refreshKey, canSeeFinancials]);

  const askCopilot = useCallback(async () => {
    const question = copilotQuestion.trim();
    if (!shipmentId || !question) return;
    setCopilotBusy(true);
    setCopilotError(null);
    try {
      const res = await askCopilotApi(shipmentId, question);
      setCopilotAnswer(res);
    } catch (err) {
      setCopilotError(err instanceof Error ? err.message : String(err));
    } finally {
      setCopilotBusy(false);
    }
  }, [shipmentId, copilotQuestion]);

  if (!shipmentId) return null;

  return (
    <div className="fixed right-0 top-0 h-full w-96 bg-neutral-900 text-white shadow-xl z-50 overflow-y-auto p-4 border-l border-neutral-800">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Shipment Detail</h2>
        <button onClick={onClose} className="text-neutral-400 hover:text-white p-1" aria-label="Close inspector">
          ✕
        </button>
      </div>

      {loading && <p className="text-neutral-400">Loading...</p>}
      {error && <p className="text-red-400">{error}</p>}

      {shipment && (
        <div className="space-y-4">
          <div>
            <p className="text-xs text-neutral-400">Reference</p>
            <p className="font-mono">
              {shipment.reference ?? `NF-${String(shipment.id).slice(0, 8).toUpperCase()}`}
            </p>
          </div>

          <div>
            <p className="text-xs text-neutral-400">Route</p>
            <p>
              {shipment.origin} → {shipment.dest ?? shipment.destination}
            </p>
          </div>

          <div className="flex gap-4">
            <div>
              <p className="text-xs text-neutral-400">Mode</p>
              <p>{shipment.mode}</p>
            </div>
            <div>
              <p className="text-xs text-neutral-400">Status</p>
              <p>{shipment.status}</p>
            </div>
            <div>
              <p className="text-xs text-neutral-400">Containers</p>
              <p>{shipment.container_count ?? "—"}</p>
            </div>
          </div>

          {/* ─── Alerts ─────────────────────────── */}
          <section aria-label="Alerts">
            <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">
              Alerts ({alerts.length})
            </p>
            {alerts.length === 0 && (
              <p className="text-sm text-neutral-500">No alerts attached to this shipment.</p>
            )}
            <ul className="space-y-1">
              {alerts.map((a) => (
                <li
                  key={a.id}
                  className="flex items-center gap-2 text-sm border border-neutral-800 rounded px-2 py-1"
                >
                  <span
                    className="text-[10px] font-bold px-1.5 rounded"
                    style={{ color: sevColor[a.severity] ?? "#CBD5E1", background: "rgba(148,163,184,0.12)" }}
                  >
                    {a.severity}
                  </span>
                  <span className="text-neutral-400 text-xs">{a.status}</span>
                  <span className="ml-auto text-amber-200 text-xs font-semibold">
                    {fmtUsd(a.financial_exposure)}
                  </span>
                  <ProvenanceBadge provenance={a.provenance} size="xs" />
                </li>
              ))}
            </ul>
          </section>

          {/* ─── ML prediction ──────────────────── */}
          <section aria-label="Delay prediction">
            <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">
              ML delay prediction
            </p>
            {prediction ? (
              <div className="text-sm space-y-1 border border-neutral-800 rounded p-2">
                <div className="flex justify-between">
                  <span className="text-neutral-400">P50 delay</span>
                  <span className="font-semibold">{prediction.delay_p50_hours.toFixed(1)} h</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">SLA risk</span>
                  <span
                    className="font-semibold"
                    style={{
                      color:
                        prediction.sla_risk_level === "BREACH"
                          ? "#FCA5A5"
                          : prediction.sla_risk_level === "HIGH"
                            ? "#FDBA74"
                            : "#34D399",
                    }}
                  >
                    {prediction.sla_risk_level}
                  </span>
                </div>
                <div className="flex justify-between items-center text-xs">
                  <ProvenanceBadge provenance={prediction.provenance} size="xs" />
                  {prediction.model_version && (
                    <span className="text-neutral-500">v{prediction.model_version}</span>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-neutral-500">Prediction unavailable (model offline).</p>
            )}
          </section>

          {/* ─── Financials (ADMIN / OPERATOR only) */}
          <section aria-label="Financials">
            <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">
              Financials
            </p>
            {!canSeeFinancials || financialsDenied ? (
              <p className="text-sm text-neutral-500">Financial detail requires an operator role.</p>
            ) : financials ? (
              <div className="text-sm space-y-1 border border-neutral-800 rounded p-2">
                <div className="flex justify-between">
                  <span className="text-neutral-400">Revenue</span>
                  <span>{fmtUsd(financials.pnl.revenue_usd)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">Shipping</span>
                  <span>{fmtUsd(financials.pnl.shipping_cost_usd)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">Freight</span>
                  <span>{fmtUsd(financials.pnl.freight_cost_usd)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">SLA penalty</span>
                  <span className={financials.pnl.sla_penalty_usd > 0 ? "text-red-300" : undefined}>
                    {fmtUsd(financials.pnl.sla_penalty_usd)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">Demurrage</span>
                  <span>{fmtUsd(financials.pnl.demurrage_usd)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-neutral-400">Carbon</span>
                  <span>{fmtUsd(financials.pnl.carbon_cost_usd)}</span>
                </div>
                <div className="flex justify-between border-t border-neutral-800 pt-1 mt-1">
                  <span className="text-neutral-400">Margin</span>
                  <span
                    className="font-bold"
                    style={{ color: financials.pnl.margin_usd >= 0 ? "#34D399" : "#FCA5A5" }}
                  >
                    {fmtUsd(financials.pnl.margin_usd)}{" "}
                    {financials.pnl.margin_pct != null &&
                      `(${(financials.pnl.margin_pct * 100).toFixed(1)}%)`}
                  </span>
                </div>
                {financials.orders.length > 0 && (
                  <details className="text-xs text-neutral-400">
                    <summary className="cursor-pointer">
                      {financials.orders.length} order(s) · {financials.container_count}×
                      {financials.container_weight_t}t containers
                    </summary>
                    <ul className="pl-4 mt-1 space-y-0.5">
                      {financials.orders.map((o) => (
                        <li key={o.order_number}>
                          {o.order_number}: {fmtUsd(o.revenue)} — {o.sla_status}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            ) : (
              <p className="text-sm text-neutral-500">Loading…</p>
            )}
          </section>

          {/* ─── AI Copilot ─────────────────────── */}
          <section aria-label="AI copilot">
            <p className="text-xs text-neutral-400 uppercase tracking-wide mb-1">
              AI copilot
            </p>
            <div className="space-y-2">
              <div className="flex gap-1">
                <input
                  value={copilotQuestion}
                  onChange={(e) => setCopilotQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && askCopilot()}
                  placeholder={COPILOT_PLACEHOLDER}
                  className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1.5 text-sm"
                  disabled={copilotBusy}
                />
                <button
                  onClick={askCopilot}
                  disabled={copilotBusy || !copilotQuestion.trim()}
                  className="bg-sky-800 hover:bg-sky-700 disabled:opacity-40 rounded px-3 text-sm font-semibold"
                >
                  {copilotBusy ? "…" : "Ask"}
                </button>
              </div>
              {copilotError && <p className="text-xs text-red-400">{copilotError}</p>}
              {copilotAnswer && (
                <div className="border border-neutral-800 rounded p-2 space-y-1">
                  <p className="text-sm whitespace-pre-wrap">{copilotAnswer.answer}</p>
                  <div className="flex items-center gap-2">
                    <ProvenanceBadge provenance={copilotAnswer.provenance} size="xs" />
                    <span className="text-[10px] text-neutral-500">
                      source: {copilotAnswer.source}
                    </span>
                  </div>
                </div>
              )}
            </div>
          </section>

          <div>
            <p className="text-xs text-neutral-400">Route version</p>
            <p className="text-sm">{shipment.route_version ?? 1}</p>
          </div>

          {shipment.legs && shipment.legs.length > 0 && (
            <div>
              <p className="text-xs text-neutral-400 mb-1">Route plan</p>
              <ul className="space-y-1 text-xs">
                {shipment.legs.map((leg) => (
                  <li
                    key={String(leg.id)}
                    className="border border-neutral-800 rounded p-2"
                  >
                    <p className="font-medium">{leg.mode}</p>
                    <p className="text-neutral-400">
                      {leg.planned_departure
                        ? new Date(leg.planned_departure).toLocaleString()
                        : "TBD"}
                      {" → "}
                      {leg.planned_arrival
                        ? new Date(leg.planned_arrival).toLocaleString()
                        : "TBD"}
                    </p>
                    <p className="text-neutral-500">
                      {leg.origin} → {leg.destination}
                    </p>
                    <p className="text-neutral-600">
                      {leg.distance_km ? `${leg.distance_km.toFixed(0)} km · ` : ""}
                      {leg.status}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* ─── Route alternatives (multimodal planner) ─── */}
          <section
            aria-label="Route alternatives"
            style={{ borderTop: '1px solid rgba(148,163,184,0.12)', paddingTop: 12 }}
          >
            <RouteAlternativesPanel
              shipmentId={shipmentId}
              refreshKey={refreshKey}
              showTabs
            />
          </section>
        </div>
      )}
    </div>
  );
}

