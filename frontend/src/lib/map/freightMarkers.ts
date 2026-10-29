/**
 * Chartroom freight markers — scaled, high-contrast silhouettes with solid
 * light background disc for sharp readability across paper and vector maps.
 *
 * Design rules:
 *   · Consistent ink/cobalt palette for operational precision.
 *   · Fill is --cobalt (#2547C8), outline is --ink (#16181D).
 *   · Solid white/paper circular disc behind silhouette ensures high light-contrast against map tiles.
 *   · Interior cut-outs in --paper (#FFFFFF) provide crisp visual structure.
 *   · SLA ring treatment:
 *       - nominal: 1px ink ring
 *       - at_risk: dashed ink ring
 *       - breached: 2px solid ink ring
 *   · Scaled to 32px for clear readability.
 */

/** Chartroom tokens, mirrored from globals.css :root. */
export const CHARTROOM = {
  paper: '#FFFFFF',
  ink: '#16181D',
  cobalt: '#2547C8',
  cobaltPressed: '#1D3AA6',
  hairline: '#D4D5D0',
} as const;

export type FreightAsset = 'VESSEL' | 'TRUCK' | 'FLIGHT' | 'TRAIN';

/** Ring treatment communicates SLA state. */
export type MarkerState = 'nominal' | 'at_risk' | 'breached';

function ringFor(state: MarkerState): { stroke: string; dash: string; width: number } {
  switch (state) {
    case 'at_risk':
      return { stroke: CHARTROOM.ink, dash: '2 1.5', width: 1.25 };
    case 'breached':
      return { stroke: CHARTROOM.ink, dash: 'none', width: 2 };
    default:
      return { stroke: CHARTROOM.ink, dash: 'none', width: 1 };
  }
}

/**
 * Bold, high-contrast silhouettes on a 24×24 grid.
 * Solid cobalt body with white cutouts for sharp recognition.
 */
function bodyFor(asset: FreightAsset): string {
  const fill = CHARTROOM.cobalt;
  const cut = CHARTROOM.paper;

  switch (asset) {
    case 'VESSEL':
      // Bold container cargo ship: bulbous bow cutwater, cargo bay grid, aft bridge.
      return `
        <path d="M12 2.2 C9.2 6.8 7.8 12.5 7.8 18.2 C7.8 20.4 9.5 21.4 12 21.4 C14.5 21.4 16.2 20.4 16.2 18.2 C16.2 12.5 14.8 6.8 12 2.2 Z" fill="${fill}"/>
        <polygon points="12,2.8 11.2,4.8 12.8,4.8" fill="${cut}"/>
        <rect x="9.4" y="6.4" width="2.3" height="3.2" rx="0.3" fill="${cut}"/>
        <rect x="12.3" y="6.4" width="2.3" height="3.2" rx="0.3" fill="${cut}"/>
        <rect x="9.4" y="10.2" width="2.3" height="3.2" rx="0.3" fill="${cut}"/>
        <rect x="12.3" y="10.2" width="2.3" height="3.2" rx="0.3" fill="${cut}"/>
        <rect x="9.6" y="14.4" width="4.8" height="2.8" rx="0.4" fill="${cut}"/>
        <rect x="11.2" y="18.0" width="1.6" height="1.4" rx="0.2" fill="${cut}"/>
      `;
    case 'TRUCK':
      // Class-8 heavy cargo semi-truck: tractor cab, mirrors, 53ft trailer container.
      return `
        <path d="M8.0 2.2 C8.0 1.8 8.5 1.4 9.2 1.4 H14.8 C15.5 1.4 16.0 1.8 16.0 2.2 V6.8 H8.0 Z" fill="${fill}"/>
        <rect x="9.2" y="2.5" width="5.6" height="2.0" rx="0.3" fill="${cut}"/>
        <line x1="6.8" y1="4.0" x2="8.0" y2="4.0" stroke="${fill}" stroke-width="1.0"/>
        <line x1="16.0" y1="4.0" x2="17.2" y2="4.0" stroke="${fill}" stroke-width="1.0"/>
        <rect x="6.6" y="7.6" width="10.8" height="13.8" rx="0.8" fill="${fill}"/>
        <line x1="7.8" y1="10.2" x2="16.2" y2="10.2" stroke="${cut}" stroke-width="0.85"/>
        <line x1="7.8" y1="13.2" x2="16.2" y2="13.2" stroke="${cut}" stroke-width="0.85"/>
        <line x1="7.8" y1="16.2" x2="16.2" y2="16.2" stroke="${cut}" stroke-width="0.85"/>
        <line x1="7.8" y1="19.2" x2="16.2" y2="19.2" stroke="${cut}" stroke-width="0.85"/>
      `;
    case 'TRAIN':
      // Locomotive engine and intermodal container consist.
      return `
        <rect x="6.4" y="2.2" width="11.2" height="13.4" rx="1.4" fill="${fill}"/>
        <path d="M8.0 3.4 H16.0 V5.2 C16.0 5.6 15.6 6.0 15.2 6.0 H8.8 C8.4 6.0 8.0 5.6 8.0 5.2 Z" fill="${cut}"/>
        <circle cx="9.6" cy="4.4" r="0.6" fill="${fill}"/>
        <circle cx="14.4" cy="4.4" r="0.6" fill="${fill}"/>
        <rect x="7.8" y="7.4" width="8.4" height="3.2" rx="0.4" fill="${cut}"/>
        <line x1="9.9" y1="7.4" x2="9.9" y2="10.6" stroke="${fill}" stroke-width="0.6"/>
        <line x1="12.0" y1="7.4" x2="12.0" y2="10.6" stroke="${fill}" stroke-width="0.6"/>
        <line x1="14.1" y1="7.4" x2="14.1" y2="10.6" stroke="${fill}" stroke-width="0.6"/>
        <rect x="7.8" y="11.4" width="8.4" height="2.8" rx="0.4" fill="${cut}"/>
        <path d="M4.4 17.6 H19.6" stroke="${fill}" stroke-width="1.6" stroke-linecap="round"/>
        <path d="M4.4 20.6 H19.6" stroke="${fill}" stroke-width="1.6" stroke-linecap="round"/>
        <line x1="6.6" y1="16.8" x2="6.6" y2="21.4" stroke="${cut}" stroke-width="0.9"/>
        <line x1="10.2" y1="16.8" x2="10.2" y2="21.4" stroke="${cut}" stroke-width="0.9"/>
        <line x1="13.8" y1="16.8" x2="13.8" y2="21.4" stroke="${cut}" stroke-width="0.9"/>
        <line x1="17.4" y1="16.8" x2="17.4" y2="21.4" stroke="${cut}" stroke-width="0.9"/>
      `;
    case 'FLIGHT':
    default:
      // High-aspect swept-wing widebody cargo freighter with twin turbofan engines.
      return `
        <path d="M12 1.8 C11.3 1.8 10.8 2.6 10.8 3.8 V8.6 L2.2 13.8 V15.6 L10.8 12.8 V18.6 L8.2 20.4 V21.8 L12 21.0 L15.8 21.8 V20.4 L13.2 18.6 V12.8 L21.8 15.6 V13.8 L13.2 8.6 V3.8 C13.2 2.6 12.7 1.8 12 1.8 Z" fill="${fill}"/>
        <rect x="7.2" y="11.2" width="1.6" height="3.2" rx="0.6" fill="${cut}"/>
        <rect x="15.2" y="11.2" width="1.6" height="3.2" rx="0.6" fill="${cut}"/>
        <polygon points="12,2.8 11.4,4.6 12.6,4.6" fill="${cut}"/>
      `;
  }
}

/**
 * Full marker HTML for a moving freight asset.
 *
 * @param asset    mode silhouette to draw
 * @param heading  degrees clockwise from north; the marker rotates to match
 * @param state    SLA treatment applied to the hairline ring
 * @param size     outer box in px (default 32)
 */
export function freightMarkerHtml(
  asset: FreightAsset,
  heading = 0,
  state: MarkerState = 'nominal',
  size = 32
): string {
  const ring = ringFor(state);
  const rot = Number.isFinite(heading) ? heading : 0;
  const dashAttr = ring.dash === 'none' ? '' : ` stroke-dasharray="${ring.dash}"`;

  return (
    `<div style="width:${size}px;height:${size}px;display:flex;align-items:center;justify-content:center;pointer-events:none;">` +
      `<svg width="${size}" height="${size}" viewBox="0 0 24 24" style="transform:rotate(${rot}deg);transform-origin:50% 50%;">` +
        `<circle cx="12" cy="12" r="10.8" fill="${CHARTROOM.paper}" stroke="${ring.stroke}" stroke-width="${ring.width}"${dashAttr}/>` +
        bodyFor(asset) +
      `</svg>` +
    `</div>`
  );
}

/**
 * Static node marker (port / warehouse / airport): a hairline ink square with
 * a cobalt core. Deliberately geometric so it never competes with a vessel.
 */
export function freightNodeHtml(kind: 'PORT' | 'WAREHOUSE' | 'AIRPORT', size = 16): string {
  const s = size;
  const core = kind === 'PORT' ? CHARTROOM.cobalt : kind === 'AIRPORT' ? CHARTROOM.cobaltPressed : CHARTROOM.ink;
  const shape =
    kind === 'WAREHOUSE'
      ? `<rect x="3" y="3" width="10" height="10" fill="${core}"/>`
      : kind === 'AIRPORT'
        ? `<path d="M8 2.6 L13.4 13.4 H2.6 Z" fill="${core}"/>`
        : `<circle cx="8" cy="8" r="4.6" fill="${core}"/>`;

  return (
    `<div style="width:${s}px;height:${s}px;pointer-events:none;">` +
      `<svg width="${s}" height="${s}" viewBox="0 0 16 16">` +
        `<rect x="0.5" y="0.5" width="15" height="15" fill="${CHARTROOM.paper}" stroke="${CHARTROOM.hairline}" stroke-width="1"/>` +
        shape +
      `</svg>` +
    `</div>`
  );
}

/**
 * Paint spec for maplibre circle layers that used to glow.
 * Flat cobalt, hairline ink stroke, constant opacity — no `circle-blur`.
 */
export function flatCirclePaint(opts?: {
  radius?: number;
  color?: string;
  strokeColor?: string;
  strokeWidth?: number;
}): Record<string, unknown> {
  return {
    'circle-radius': opts?.radius ?? 4,
    'circle-color': opts?.color ?? CHARTROOM.cobalt,
    'circle-opacity': 1,
    'circle-stroke-width': opts?.strokeWidth ?? 1,
    'circle-stroke-color': opts?.strokeColor ?? CHARTROOM.ink,
    'circle-stroke-opacity': 0.55,
  };
}
