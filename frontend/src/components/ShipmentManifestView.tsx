'use client';

import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Ship,
  Plane,
  Truck,
  Search,
  AlertTriangle,
  ArrowRight,
  Clock,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
} from 'lucide-react';
import {
  getShipments,
  type ShipmentListItem,
  type TransportMode,
  type ShipmentStatus,
} from '@/lib/nexafreight';
import { formatInrCompact, usdToInr } from '@/lib/format/inr';
import { ProvenanceChip } from '@/components/ProvenanceBadge';
import LoadingGlobe from '@/components/illustrations/LoadingGlobe';
import PlexusHeader from '@/components/illustrations/PlexusHeader';

interface ShipmentManifestViewProps {
  onSelectShipment: (shipmentId: string) => void;
  selectedShipmentId: string | null;
}

const MODE_ICONS: Record<string, typeof Ship> = {
  SEA: Ship,
  AIR: Plane,
  ROAD: Truck,
  RAIL: Truck,
};

function computeShipmentRiskAndConfidence(item: ShipmentListItem): {
  risk: 'LOW' | 'MEDIUM' | 'HIGH';
  confidencePct: number;
} {
  if (item.status === 'DELAYED') {
    return { risk: 'HIGH', confidencePct: 32 };
  }
  if (!item.strictest_sla_deadline || !item.revised_eta) {
    return { risk: 'LOW', confidencePct: 88 };
  }
  const sla = new Date(item.strictest_sla_deadline).getTime();
  const eta = new Date(item.revised_eta).getTime();
  const diffHours = (sla - eta) / (1000 * 60 * 60);

  if (diffHours < 0) {
    return { risk: 'HIGH', confidencePct: 24 };
  } else if (diffHours < 24) {
    return { risk: 'MEDIUM', confidencePct: 64 };
  } else {
    return { risk: 'LOW', confidencePct: 94 };
  }
}

function estimateShipmentCostUsd(item: ShipmentListItem): number {
  if (item.estimated_cost != null && item.estimated_cost > 0) {
    return item.estimated_cost;
  }
  // Calibrated transport freight benchmark by mode
  switch (item.mode) {
    case 'AIR': return 6500;
    case 'SEA': return 2100;
    case 'RAIL': return 1550;
    case 'ROAD': return 1100;
    default: return 1800;
  }
}

export default function ShipmentManifestView({
  onSelectShipment,
  selectedShipmentId,
}: ShipmentManifestViewProps) {
  const [shipments, setShipments] = useState<ShipmentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination & Filters
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | ShipmentStatus>('ALL');
  const [modeFilter, setModeFilter] = useState<'ALL' | TransportMode>('ALL');

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getShipments({
        page,
        size: pageSize,
        status: statusFilter === 'ALL' ? undefined : statusFilter,
        mode: modeFilter === 'ALL' ? undefined : modeFilter,
      });
      setShipments(res.items || []);
      setTotal(res.total ?? (res.items || []).length);
      setTotalPages(res.total_pages ?? Math.max(1, Math.ceil((res.total ?? 0) / pageSize)));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load shipments manifest';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, modeFilter]);

  useEffect(() => {
    void fetchList();
  }, [fetchList]);

  // Listen for auth_success event so manifest loads when credentials hydrate
  useEffect(() => {
    const handler = () => { void fetchList(); };
    if (typeof globalThis.window !== 'undefined') {
      globalThis.window.addEventListener('nexafreight:auth_success', handler);
      return () => globalThis.window.removeEventListener('nexafreight:auth_success', handler);
    }
  }, [fetchList]);

  // Client-side text filter on current page rows
  const filteredShipments = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    if (!q) return shipments;
    return shipments.filter((item) => {
      const id = (item.id || '').toLowerCase();
      const origin = (item.origin || '').toLowerCase();
      const dest = (item.destination || '').toLowerCase();
      return id.includes(q) || origin.includes(q) || dest.includes(q);
    });
  }, [shipments, searchQuery]);

  return (
    <div
      className="flex flex-col h-full w-full overflow-hidden select-none"
      style={{
        backgroundColor: 'var(--paper)',
        color: 'var(--ink)',
      }}
    >
      {/* Header bar with faint PlexusHeader background */}
      <div
        className="relative flex items-center justify-between px-6 py-4 border-b flex-shrink-0 overflow-hidden"
        style={{ borderColor: 'var(--border-hairline)' }}
      >
        <PlexusHeader />

        <div className="relative z-10 flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/nexafreight-mark.svg" alt="NexaFreight" className="w-5 h-5 rounded-[2px]" />
            <h1 className="font-ui text-[18px] font-semibold tracking-tight text-[var(--ink)]">
              Shipment Manifest & Waybill Ledger
            </h1>
            <span className="font-mono text-[11px] px-1.5 py-0.5 rounded-[2px] bg-[var(--bg-subtle)] border border-[var(--border-hairline)] text-[var(--text-secondary)]">
              {total} TOTAL WAYBILLS
            </span>
          </div>
          <p className="font-ui text-[12px] text-[var(--text-secondary)]">
            Multimodal container tracking across global ocean corridors, air freights, and road haulage.
          </p>
        </div>

        <div className="relative z-10 flex items-center gap-3">
          <button
            onClick={() => void fetchList()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-[2px] text-[12px] font-mono border transition-colors hover:bg-black/5"
            style={{ borderColor: 'var(--border-hairline)', color: 'var(--ink)' }}
            title="Refresh list"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>REFRESH</span>
          </button>
        </div>
      </div>

      {/* Control / Filter Bar */}
      <div
        className="flex flex-wrap items-center justify-between gap-3 px-6 py-2.5 border-b flex-shrink-0"
        style={{
          borderColor: 'var(--border-hairline)',
          backgroundColor: 'var(--bg-subtle)',
        }}
      >
        {/* Search */}
        <div className="relative flex-1 min-w-[240px] max-w-[360px]">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
          <input
            type="text"
            placeholder="Search waybill ID or UN/LOCODE (e.g. INNSA, AEJEA)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1 text-[12px] font-mono rounded-[2px] border focus:outline-none focus:border-[var(--cobalt)] transition-colors"
            style={{
              backgroundColor: 'var(--paper)',
              borderColor: 'var(--border-hairline)',
              color: 'var(--ink)',
            }}
          />
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Status Filter */}
          <div
            className="flex items-center rounded-[2px] border overflow-hidden p-0.5 gap-0.5"
            style={{ borderColor: 'var(--border-hairline)', backgroundColor: 'var(--paper)' }}
          >
            {(['ALL', 'IN_TRANSIT', 'DELAYED', 'PLANNED', 'DELIVERED'] as const).map((st) => (
              <button
                key={st}
                onClick={() => {
                  setStatusFilter(st);
                  setPage(1);
                }}
                className={`px-2 py-0.5 text-[11px] font-mono rounded-[2px] transition-colors ${
                  statusFilter === st
                    ? 'bg-[var(--cobalt)] text-white font-semibold'
                    : 'text-[var(--text-secondary)] hover:text-[var(--ink)]'
                }`}
              >
                {st}
              </button>
            ))}
          </div>

          {/* Mode Filter */}
          <div
            className="flex items-center rounded-[2px] border overflow-hidden p-0.5 gap-0.5"
            style={{ borderColor: 'var(--border-hairline)', backgroundColor: 'var(--paper)' }}
          >
            {(['ALL', 'SEA', 'AIR', 'ROAD'] as const).map((md) => (
              <button
                key={md}
                onClick={() => {
                  setModeFilter(md);
                  setPage(1);
                }}
                className={`px-2 py-0.5 text-[11px] font-mono rounded-[2px] transition-colors ${
                  modeFilter === md
                    ? 'bg-[var(--ink)] text-white font-semibold'
                    : 'text-[var(--text-secondary)] hover:text-[var(--ink)]'
                }`}
              >
                {md}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Main Table / Ledger */}
      <div className="flex-1 overflow-y-auto relative">
        {loading && shipments.length === 0 ? (
          <div className="flex items-center justify-center h-full min-h-[360px]">
            <LoadingGlobe caption="QUERYING CARRIER WAYBILL LEDGER..." size={240} />
          </div>
        ) : error ? (
          <div className="p-8 text-center text-[var(--oxide-risk)] font-mono text-[12px]">
            <div className="p-4 rounded-[2px] border border-[var(--oxide-risk)] bg-red-50/50 inline-block max-w-md">
              {error}
            </div>
          </div>
        ) : filteredShipments.length === 0 ? (
          <div className="py-24 text-center text-[var(--text-secondary)] font-mono text-[12px]">
            No shipments matched your search criteria.
          </div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr
                className="border-b font-mono text-[10px] text-[var(--text-secondary)] uppercase tracking-wider sticky top-0 z-10"
                style={{
                  backgroundColor: 'var(--bg-subtle)',
                  borderColor: 'var(--border-hairline)',
                }}
              >
                <th className="py-2.5 px-6 font-medium">Waybill ID</th>
                <th className="py-2.5 px-4 font-medium">Lane Corridor</th>
                <th className="py-2.5 px-4 font-medium">Mode</th>
                <th className="py-2.5 px-4 font-medium">Status</th>
                <th className="py-2.5 px-4 font-medium">ETA Window</th>
                <th className="py-2.5 px-4 font-medium">Confidence</th>
                <th className="py-2.5 px-4 font-medium">Risk Level</th>
                <th className="py-2.5 px-4 font-medium">Est. Cost (₹)</th>
                <th className="py-2.5 px-6 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-hairline)] font-mono text-[12px]">
              {filteredShipments.map((shipment) => {
                const isSelected = selectedShipmentId === shipment.id;
                const ModeIcon = MODE_ICONS[shipment.mode] || Ship;
                const isDelayed = shipment.status === 'DELAYED';
                const { risk, confidencePct } = computeShipmentRiskAndConfidence(shipment);
                const costInr = usdToInr(estimateShipmentCostUsd(shipment));

                return (
                  <tr
                    key={shipment.id}
                    onClick={() => onSelectShipment(shipment.id)}
                    className={`cursor-pointer transition-colors hover:bg-[var(--bg-subtle)] ${
                      isSelected ? 'bg-[rgba(37,71,200,0.06)]' : ''
                    }`}
                  >
                    {/* 1. ID */}
                    <td className="py-3 px-6 font-bold text-[var(--ink)]">
                      <div className="flex items-center gap-1.5">
                        {isDelayed && (
                          <AlertTriangle className="w-3.5 h-3.5 text-[var(--oxide-risk)] flex-shrink-0" />
                        )}
                        <span className="hover:text-[var(--cobalt)] transition-colors">
                          NF-{shipment.id.slice(0, 8).toUpperCase()}
                        </span>
                      </div>
                    </td>

                    {/* 2. Lane */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5 font-mono text-[11px] text-[var(--ink)]">
                        <span className="font-semibold">{shipment.origin || 'ORIGIN'}</span>
                        <ArrowRight className="w-3 h-3 text-[var(--text-secondary)]" />
                        <span className="font-semibold">{shipment.destination || 'DEST'}</span>
                      </div>
                    </td>

                    {/* 3. Mode */}
                    <td className="py-3 px-4">
                      <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-[2px] bg-[var(--bg-subtle)] border border-[var(--border-hairline)] text-[11px]">
                        <ModeIcon className="w-3 h-3 text-[var(--cobalt)]" />
                        <span>{shipment.mode}</span>
                      </div>
                    </td>

                    {/* 4. Status */}
                    <td className="py-3 px-4">
                      <span
                        className="inline-block px-1.5 py-0.5 rounded-[2px] font-mono text-[10px] font-bold tracking-wider uppercase border"
                        style={{
                          backgroundColor:
                            shipment.status === 'DELAYED'
                              ? 'rgba(180, 69, 47, 0.08)'
                              : shipment.status === 'DELIVERED'
                              ? 'rgba(62, 107, 79, 0.08)'
                              : 'rgba(37, 71, 200, 0.08)',
                          borderColor:
                            shipment.status === 'DELAYED'
                              ? 'var(--oxide-risk)'
                              : shipment.status === 'DELIVERED'
                              ? 'var(--moss-positive)'
                              : 'var(--cobalt)',
                          color:
                            shipment.status === 'DELAYED'
                              ? 'var(--oxide-risk)'
                              : shipment.status === 'DELIVERED'
                              ? 'var(--moss-positive)'
                              : 'var(--cobalt)',
                        }}
                      >
                        {shipment.status}
                      </span>
                    </td>

                    {/* 5. ETA Window */}
                    <td className="py-3 px-4">
                      <div className="flex flex-col gap-0.5 font-mono text-[11px]">
                        <div className="flex items-center gap-1 text-[var(--ink)]">
                          <Clock className="w-3 h-3 text-[var(--text-secondary)]" />
                          <span className={isDelayed ? 'text-[var(--oxide-risk)] font-semibold' : ''}>
                            {shipment.revised_eta
                              ? new Date(shipment.revised_eta).toLocaleDateString('en-GB', {
                                  day: '2-digit',
                                  month: 'short',
                                  hour: '2-digit',
                                  minute: '2-digit',
                                })
                              : 'ON TRACK'}
                          </span>
                        </div>
                        {shipment.strictest_sla_deadline && (
                          <span className="text-[10px] text-[var(--text-secondary)]">
                            SLA: {new Date(shipment.strictest_sla_deadline).toLocaleDateString('en-GB', {
                              day: '2-digit',
                              month: 'short',
                            })}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* 6. Confidence Bar */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2">
                        <div className="w-12 h-1.5 rounded-[1px] bg-[var(--border-hairline)] overflow-hidden">
                          <div
                            className="h-full rounded-[1px] transition-all"
                            style={{
                              width: `${confidencePct}%`,
                              backgroundColor:
                                confidencePct > 75
                                  ? 'var(--moss-positive)'
                                  : confidencePct > 45
                                  ? 'var(--cobalt)'
                                  : 'var(--oxide-risk)',
                            }}
                          />
                        </div>
                        <span className="tabular-nums text-[10px] text-[var(--text-secondary)]">
                          {confidencePct}%
                        </span>
                      </div>
                    </td>

                    {/* 7. Risk Level */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="px-1.5 py-0.5 rounded-[2px] font-mono text-[10px] font-bold border"
                          style={{
                            backgroundColor:
                              risk === 'HIGH'
                                ? 'rgba(180, 69, 47, 0.08)'
                                : risk === 'MEDIUM'
                                ? 'rgba(217, 119, 6, 0.08)'
                                : 'rgba(62, 107, 79, 0.08)',
                            borderColor:
                              risk === 'HIGH'
                                ? 'var(--oxide-risk)'
                                : risk === 'MEDIUM'
                                ? '#D97706'
                                : 'var(--moss-positive)',
                            color:
                              risk === 'HIGH'
                                ? 'var(--oxide-risk)'
                                : risk === 'MEDIUM'
                                ? '#D97706'
                                : 'var(--moss-positive)',
                          }}
                        >
                          {risk}
                        </span>
                        <ProvenanceChip provenance="DERIVED" size="xs" />
                      </div>
                    </td>

                    {/* 8. Est. Cost in ₹ */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-[12px] font-semibold text-[var(--ink)] tabular-nums">
                          {formatInrCompact(costInr)}
                        </span>
                        <ProvenanceChip provenance="DERIVED" size="xs" />
                      </div>
                    </td>

                    {/* 9. Action */}
                    <td className="py-3 px-6 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectShipment(shipment.id);
                        }}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-ui font-medium rounded-[2px] border text-[var(--cobalt)] hover:bg-[var(--cobalt)] hover:text-white transition-colors"
                        style={{ borderColor: 'var(--cobalt)' }}
                      >
                        <span>DOSSIER</span>
                        <ExternalLink className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination Footer Strip */}
      <div
        className="flex items-center justify-between px-6 py-2.5 border-t flex-shrink-0 font-mono text-[11px]"
        style={{
          borderColor: 'var(--border-hairline)',
          backgroundColor: 'var(--bg-subtle)',
        }}
      >
        <div className="flex items-center gap-3 text-[var(--text-secondary)]">
          <span>
            Showing{' '}
            <strong className="text-[var(--ink)]">
              {total === 0 ? 0 : (page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)}
            </strong>{' '}
            of <strong className="text-[var(--ink)]">{total}</strong> waybills
          </span>

          <div className="hidden sm:flex items-center gap-1.5 pl-3 border-l border-[var(--border-hairline)]">
            <span>Per page:</span>
            {[20, 50, 100].map((sz) => (
              <button
                key={sz}
                onClick={() => {
                  setPageSize(sz);
                  setPage(1);
                }}
                className={`px-1.5 py-0.5 rounded-[2px] transition-colors ${
                  pageSize === sz
                    ? 'bg-[var(--cobalt)] text-white font-bold'
                    : 'text-[var(--text-secondary)] hover:text-[var(--ink)]'
                }`}
              >
                {sz}
              </button>
            ))}
          </div>
        </div>

        {/* Previous / Next Controls */}
        <div className="flex items-center gap-2">
          <span className="text-[var(--text-secondary)] mr-2">
            Page <strong className="text-[var(--ink)]">{page}</strong> of{' '}
            <strong className="text-[var(--ink)]">{Math.max(1, totalPages)}</strong>
          </span>

          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || loading}
            className="flex items-center gap-1 px-2 py-1 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--paper)] text-[var(--ink)] disabled:opacity-40 disabled:cursor-not-allowed hover:bg-black/5 transition-colors"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">PREV</span>
          </button>

          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || loading}
            className="flex items-center gap-1 px-2 py-1 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--paper)] text-[var(--ink)] disabled:opacity-40 disabled:cursor-not-allowed hover:bg-black/5 transition-colors"
          >
            <span className="hidden sm:inline">NEXT</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
