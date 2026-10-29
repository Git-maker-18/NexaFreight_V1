'use client';

import { memo, useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  Compass,
  Package,
  AlertTriangle,
  BarChart3,
  LogOut,
  User as UserIcon,
} from 'lucide-react';
import type { User } from '@/lib/nexafreight/types';
import { useAuthStore } from '@/store/useAuthStore';
import { getAlerts } from '@/lib/nexafreight';

export type WorkspaceScreen = 'map' | 'shipments' | 'disruptions' | 'analytics' | 'calibration';

interface TacticalNavRailProps {
  activeScreen?: WorkspaceScreen;
  onSelectScreen?: (screen: WorkspaceScreen) => void;
  alertCount?: number;
  user?: User | null;
  onLogout?: () => void;
}

interface NavItemDef {
  key: string;
  href: string;
  label: string;
  sublabel: string;
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  shortcut: string;
  badge?: number;
}

function TacticalNavRailComponent({
  activeScreen: legacyActiveScreen,
  onSelectScreen,
  alertCount: propAlertCount,
  user: propUser,
  onLogout: propOnLogout,
}: TacticalNavRailProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user: authUser, clearAuth } = useAuthStore();
  const currentUser = propUser !== undefined ? propUser : authUser;

  const [internalAlertCount, setInternalAlertCount] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    const fetchCount = async () => {
      try {
        const res = await getAlerts({ status: 'OPEN' });
        if (!cancelled && res?.alerts) {
          setInternalAlertCount(res.alerts.length);
        }
      } catch {}
    };
    fetchCount();
    const iv = setInterval(fetchCount, 30000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, []);

  const effectiveAlertCount = propAlertCount !== undefined ? propAlertCount : internalAlertCount;

  // Keyboard navigation between routes (1–4)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as Element)?.tagName)) return;
      if (e.key === '1') router.push('/');
      if (e.key === '2') router.push('/shipments');
      if (e.key === '3') router.push('/alerts');
      if (e.key === '4') router.push('/insights');
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [router]);

  // Don't render the rail on login screen
  if (pathname === '/login') return null;

  const navItems: NavItemDef[] = [
    {
      key: 'overview',
      href: '/',
      label: 'Control Tower',
      sublabel: 'Tactical Map & AIS Telemetry',
      icon: Compass,
      shortcut: '1',
    },
    {
      key: 'shipments',
      href: '/shipments',
      label: 'Shipment Manifest',
      sublabel: 'Milestone Waybills & Legs',
      icon: Package,
      shortcut: '2',
    },
    {
      key: 'alerts',
      href: '/alerts',
      label: 'Disruption Center',
      sublabel: 'Active Breaches & Recovery',
      icon: AlertTriangle,
      shortcut: '3',
      badge: effectiveAlertCount > 0 ? effectiveAlertCount : undefined,
    },
    {
      key: 'insights',
      href: '/insights',
      label: 'Operational Analytics',
      sublabel: 'Demurrage, SLA & CO2 Ledger',
      icon: BarChart3,
      shortcut: '4',
    },
  ];

  const handleLogout = () => {
    if (propOnLogout) {
      propOnLogout();
    } else {
      clearAuth();
      router.replace('/login');
    }
  };

  const isItemActive = (item: NavItemDef) => {
    if (legacyActiveScreen) {
      if (item.href === '/' && legacyActiveScreen === 'map') return true;
      if (item.href === '/shipments' && legacyActiveScreen === 'shipments') return true;
      if (item.href === '/alerts' && legacyActiveScreen === 'disruptions') return true;
      if (item.href === '/insights' && legacyActiveScreen === 'analytics') return true;
    }
    if (item.href === '/') {
      return pathname === '/';
    }
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
  };

  return (
    <aside
      className="fixed left-0 top-0 bottom-0 w-[58px] z-[1060] flex flex-col justify-between items-center py-3 select-none"
      style={{
        backgroundColor: 'var(--paper)',
        borderRight: '1px solid var(--border-hairline)',
        boxShadow: 'none',
      }}
      aria-label="Tactical Workspace Navigation"
    >
      {/* Top: Brand Monogram */}
      <div className="flex flex-col items-center gap-3 w-full">
        <Link
          href="/"
          className="w-9 h-9 flex items-center justify-center rounded-[3px] transition-transform hover:scale-105 focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--cobalt)] overflow-hidden shadow-sm"
          title="NexaFreight Control Tower"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/nexafreight-mark.svg"
            alt="NexaFreight"
            className="w-full h-full object-cover rounded-[3px]"
          />
        </Link>

        {/* Separator Hairline */}
        <div className="w-6 h-[1px]" style={{ backgroundColor: 'var(--border-hairline)' }} />

        {/* Navigation Items (Real Next.js Links) */}
        <nav className="flex flex-col gap-1.5 items-center w-full px-1">
          {navItems.map((item) => {
            const isActive = isItemActive(item);
            const Icon = item.icon;

            return (
              <Link
                key={item.key}
                href={item.href}
                onClick={() => {
                  if (onSelectScreen) {
                    if (item.href === '/') onSelectScreen('map');
                    if (item.href === '/shipments') onSelectScreen('shipments');
                    if (item.href === '/alerts') onSelectScreen('disruptions');
                    if (item.href === '/insights') onSelectScreen('analytics');
                  }
                }}
                className="relative group w-10 h-10 flex items-center justify-center rounded-[3px] transition-all focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--cobalt)]"
                style={{
                  backgroundColor: isActive ? 'var(--bg-subtle)' : 'transparent',
                  border: isActive ? '1px solid var(--border-hairline)' : '1px solid transparent',
                  color: isActive ? 'var(--cobalt)' : 'var(--text-secondary)',
                }}
                aria-current={isActive ? 'page' : undefined}
                aria-label={item.label}
              >
                {/* Active Left Indicator 2px Rule */}
                {isActive && (
                  <span
                    className="absolute left-[-5px] top-[7px] bottom-[7px] w-[2px] rounded-r-[1px]"
                    style={{ backgroundColor: 'var(--cobalt)' }}
                  />
                )}

                <Icon
                  style={{
                    width: 18,
                    height: 18,
                    strokeWidth: isActive ? 2.2 : 1.7,
                  }}
                />

                {/* Badge if present (e.g. active alerts) */}
                {item.badge !== undefined && (
                  <span
                    className="absolute -top-1 -right-1 px-1 min-w-[15px] h-[15px] flex items-center justify-center rounded-[2px] font-mono text-[9px] font-bold text-white"
                    style={{ backgroundColor: 'var(--oxide-risk)' }}
                  >
                    {item.badge}
                  </span>
                )}

                {/* Tactical Hover Flyout Tooltip (Aligned to Right - Flat, No Shadow) */}
                <div
                  className="pointer-events-none absolute left-[54px] top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-[1200] whitespace-nowrap px-2.5 py-1.5 rounded-[2px] flex flex-col gap-0.5"
                  style={{
                    backgroundColor: 'var(--ink)',
                    color: 'var(--paper)',
                    border: '1px solid var(--border-hairline)',
                    boxShadow: 'none',
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-ui text-[12px] font-semibold">{item.label}</span>
                    <span
                      className="font-mono text-[9px] px-1 py-0.2 rounded-[2px] bg-white/20 text-white"
                    >
                      [{item.shortcut}]
                    </span>
                  </div>
                  <span className="font-mono text-[10px] text-white/70">{item.sublabel}</span>
                </div>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom: Operator Profile & Session Action */}
      <div className="flex flex-col items-center gap-2 w-full px-1">
        <div className="w-6 h-[1px]" style={{ backgroundColor: 'var(--border-hairline)' }} />

        {/* User Monogram */}
        <div
          className="relative group w-9 h-9 flex items-center justify-center rounded-[3px] cursor-pointer"
          style={{
            backgroundColor: 'var(--bg-subtle)',
            border: '1px solid var(--border-hairline)',
            color: 'var(--ink)',
          }}
          title={currentUser?.email || 'Operator'}
        >
          <UserIcon style={{ width: 16, height: 16 }} />

          {/* User tooltip */}
          <div
            className="pointer-events-none absolute left-[54px] bottom-0 opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-[1200] whitespace-nowrap px-2.5 py-1.5 rounded-[2px] flex flex-col gap-0.5"
            style={{
              backgroundColor: 'var(--ink)',
              color: 'var(--paper)',
              border: '1px solid var(--border-hairline)',
              boxShadow: 'none',
            }}
          >
            <span className="font-ui text-[12px] font-semibold">{currentUser?.full_name || 'Operator'}</span>
            <span className="font-mono text-[10px] text-white/70">{currentUser?.email || 'operator@nexafreight.dev'}</span>
            <span className="font-mono text-[9px] text-[var(--moss-positive)] uppercase mt-0.5">
              Role: {currentUser?.role || 'OPERATOR'}
            </span>
          </div>
        </div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="w-8 h-8 flex items-center justify-center rounded-[3px] text-[var(--text-secondary)] hover:text-[var(--oxide-risk)] hover:bg-black/5 transition-colors"
          title="Sign Out"
          aria-label="Sign Out"
        >
          <LogOut style={{ width: 15, height: 15 }} />
        </button>
      </div>
    </aside>
  );
}

export const TacticalNavRail = memo(TacticalNavRailComponent);
export default TacticalNavRail;
