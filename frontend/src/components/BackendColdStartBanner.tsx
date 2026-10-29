'use client';

import React, { useEffect, useState, useRef } from 'react';
import { Activity, CheckCircle, RefreshCw, X } from 'lucide-react';

export default function BackendColdStartBanner() {
  const [status, setStatus] = useState<'idle' | 'waking' | 'connected' | 'dismissed'>('idle');
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let cancelled = false;
    let pollInterval: NodeJS.Timeout | null = null;
    const startTime = Date.now();

    // Threshold timer: if health check doesn't succeed within 3.5s, show "waking up"
    const coldStartTimer = setTimeout(() => {
      if (!cancelled && status !== 'connected') {
        setStatus('waking');
      }
    }, 3500);

    // Elapsed counter
    timerRef.current = setInterval(() => {
      setElapsed(Math.round((Date.now() - startTime) / 1000));
    }, 1000);

    const checkBackend = async () => {
      try {
        const res = await fetch('/api/nexa/healthz', {
          cache: 'no-store',
          signal: AbortSignal.timeout(5000),
        });

        if (res.ok) {
          if (!cancelled) {
            clearTimeout(coldStartTimer);
            if (pollInterval) clearInterval(pollInterval);
            if (timerRef.current) clearInterval(timerRef.current);

            // If we showed the waking banner, give positive confirmation before fading out
            setStatus((prev) => {
              if (prev === 'waking') {
                setTimeout(() => setStatus('dismissed'), 2500);
                return 'connected';
              }
              return 'idle'; // Was fast, never showed
            });
          }
        } else if (res.status === 502 || res.status === 503 || res.status === 504) {
          // Render gateway waiting on container
          if (!cancelled) setStatus('waking');
        }
      } catch {
        // Network timeout / waiting on cold start
        if (!cancelled && Date.now() - startTime >= 3500) {
          setStatus('waking');
        }
      }
    };

    // Initial check
    checkBackend();

    // Poll every 4 seconds while active
    pollInterval = setInterval(checkBackend, 4000);

    return () => {
      cancelled = true;
      clearTimeout(coldStartTimer);
      if (pollInterval) clearInterval(pollInterval);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  if (status === 'idle' || status === 'dismissed') {
    return null;
  }

  return (
    <aside
      aria-label="Backend Service Status"
      className="fixed bottom-4 right-4 z-50 max-w-md p-3.5 rounded-[4px] shadow-lg border backdrop-blur-md transition-all duration-300 font-mono text-[12px]"
      style={{
        backgroundColor:
          status === 'connected'
            ? 'rgba(62, 107, 79, 0.95)'
            : 'rgba(30, 36, 44, 0.95)',
        borderColor:
          status === 'connected'
            ? 'var(--moss-positive, #3E6B4F)'
            : 'var(--cobalt, #2547C8)',
        color: '#FFFFFF',
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          {status === 'connected' ? (
            <CheckCircle className="w-4 h-4 text-emerald-300 shrink-0" />
          ) : (
            <RefreshCw className="w-4 h-4 text-blue-300 animate-spin shrink-0" />
          )}
          <div>
            <div className="font-bold tracking-wide text-[11px] uppercase flex items-center gap-1.5">
              <span>{status === 'connected' ? 'CONTROL TOWER CONNECTED' : 'BACKEND WAKING UP'}</span>
              {status === 'waking' && (
                <span className="text-blue-300 text-[10px]">({elapsed}s)</span>
              )}
            </div>
            <p className="text-[11px] text-gray-200 mt-0.5 leading-snug font-sans">
              {status === 'connected'
                ? 'Backend operational. Real-time telemetry, routes & ML services active.'
                : 'Backend instance is warming up from standby (~50s on free tier). Restoring live connection...'}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setStatus('dismissed')}
          className="text-gray-400 hover:text-white p-0.5 rounded transition-colors"
          title="Dismiss status banner"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </aside>
  );
}
