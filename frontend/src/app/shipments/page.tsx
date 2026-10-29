'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import ErrorBoundary from '@/components/ErrorBoundary';
import ShipmentManifestView from '@/components/ShipmentManifestView';
import { ProvenanceChip } from '@/components/ProvenanceBadge';
import PlexusHeader from '@/components/illustrations/PlexusHeader';

function ShipmentsPageContent() {
  const router = useRouter();
  const { isAuthenticated, isHydrated } = useAuthStore();

  useEffect(() => {
    if (isHydrated && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isHydrated, isAuthenticated, router]);

  if (!isHydrated || !isAuthenticated) return null;

  return (
    <div
      className="fixed inset-0 overflow-hidden flex flex-col"
      style={{ backgroundColor: 'var(--paper)', color: 'var(--ink)' }}
    >
      <div className="pl-[58px] h-full flex flex-col relative overflow-hidden">
        {/* Cockpit Status Strip */}
        <header
          className="h-12 border-b flex items-center justify-between px-4 z-[1040] select-none flex-shrink-0 relative overflow-hidden"
          style={{
            backgroundColor: 'var(--paper)',
            borderColor: 'var(--border-hairline)',
          }}
        >
          <PlexusHeader />
          <div className="relative z-10 flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="font-ui text-[13px] font-bold tracking-wider text-[var(--ink)]">
                SHIPMENT MANIFEST
              </span>
              <span className="text-[var(--border-hairline)]">/</span>
              <span className="hidden sm:inline font-mono text-[10px] text-[var(--text-secondary)]">
                MULTIMODAL WAYBILLS & ROUTE MILESTONES
              </span>
            </div>
            <ProvenanceChip provenance="DERIVED" size="sm" />
          </div>

          <div className="flex items-center gap-2 font-mono text-[10px] text-[var(--text-secondary)]">
            <span className="px-2 py-0.5 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)]">
              LEDGER ACTIVE
            </span>
          </div>
        </header>

        {/* Full-Page Waybills Ledger */}
        <main className="flex-1 relative overflow-hidden bg-[var(--paper)]">
          <ShipmentManifestView
            onSelectShipment={(id) => router.push(`/shipments/${id}`)}
            selectedShipmentId={null}
          />
        </main>
      </div>
    </div>
  );
}

export default function ShipmentsPage() {
  return (
    <ErrorBoundary name="Shipment Manifest Ledger">
      <ShipmentsPageContent />
    </ErrorBoundary>
  );
}
