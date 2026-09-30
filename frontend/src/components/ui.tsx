import { Component, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { RARITY_COLORS, type Cosmetic, type CosmeticAsset } from '../types';

/* ---------- loading / empty / error ---------- */

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state-wrap" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function Empty({ icon = '✨', title, hint, action }: {
  icon?: string; title: string; hint?: string; action?: ReactNode;
}) {
  return (
    <div className="state-wrap">
      <div className="empty-icon" aria-hidden="true">{icon}</div>
      <h3>{title}</h3>
      {hint && <p className="muted">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state-wrap">
      <div className="empty-icon" aria-hidden="true">🛰️</div>
      <h3>Something went wrong</h3>
      <p className="muted">{message}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

/* ---------- error boundary: cosmetic failures never break the app ---------- */

interface EBState { failed: boolean; }

export class ErrorBoundary extends Component<{ children: ReactNode; fallback?: ReactNode }, EBState> {
  state: EBState = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { /* log-free: stay silent, stay up */ }
  render() {
    if (this.state.failed) return this.props.fallback ?? null;
    return this.props.children;
  }
}

/* ---------- modal ---------- */

export function Modal({ title, onClose, children }: {
  title: string; onClose: () => void; children: ReactNode;
}) {
  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

/* ---------- rarity ---------- */

export function RarityBadge({ rarity }: { rarity: string }) {
  const color = RARITY_COLORS[rarity] ?? '#9aa0a6';
  const isMythic = rarity === 'mythic';
  return (
    <span
      className={'rarity-badge' + (isMythic ? ' mythic' : '')}
      style={isMythic ? undefined : { borderColor: color, color }}
    >
      {rarity}
    </span>
  );
}

export function rarityStyle(rarity: string): CSSProperties {
  const c = RARITY_COLORS[rarity];
  if (!c) return {};
  if (c.startsWith('linear-gradient')) return { borderImage: `${c} 1`, boxShadow: '0 0 18px rgba(200,140,255,.35)' };
  return { borderColor: c, boxShadow: `0 0 14px ${c}55` };
}

/* ---------- cosmetic thumbnail (emoji + gradient, always safe) ---------- */

export function assetGradient(asset?: CosmeticAsset | null): string {
  const g = asset?.gradient;
  if (g && g.length >= 2) return `linear-gradient(135deg, ${g[0]}, ${g[1]})`;
  return 'linear-gradient(135deg, #2a2a4a, #1a1a30)';
}

export function CosmeticThumb({ cosmetic, size = 56 }: { cosmetic: Pick<Cosmetic, 'asset' | 'name' | 'rarity'> | { asset: CosmeticAsset; name: string; rarity: string }; size?: number }) {
  return (
    <div
      className="cos-thumb"
      style={{ width: size, height: size, background: assetGradient(cosmetic.asset), ...rarityStyle(cosmetic.rarity) }}
      title={cosmetic.name}
      aria-label={cosmetic.name}
    >
      <span aria-hidden="true">{cosmetic.asset?.emoji ?? '✨'}</span>
    </div>
  );
}

/* ---------- avatar with frame ---------- */

export function Avatar({ profile, size = 44 }: {
  profile: {
    display_name: string;
    avatar?: { asset?: CosmeticAsset | null; name?: string } | null;
    frame?: { asset?: CosmeticAsset | null } | null;
  } | null | undefined;
  size?: number;
}) {
  const name = profile?.display_name ?? '?';
  const initial = name.charAt(0).toUpperCase() || '?';
  const asset = profile?.avatar?.asset;
  const frameAsset = profile?.frame?.asset;
  return (
    <div
      className="avatar"
      style={{
        width: size, height: size, fontSize: size * 0.42,
        background: asset ? assetGradient(asset) : undefined,
        border: frameAsset ? `3px solid transparent` : undefined,
        boxShadow: frameAsset ? `0 0 0 2px ${'#8b7bff'}, 0 0 12px ${'#8b7bff66'}` : undefined,
      }}
      aria-label={name}
      title={name}
    >
      {asset?.emoji ?? initial}
    </div>
  );
}

/* ---------- misc ---------- */

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="section-title">
      <h2>{children}</h2>
      {right}
    </div>
  );
}

export function ProgressBar({ value, max, label }: { value: number; max: number; label?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemax={max} aria-label={label}>
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Currency({ amount, kind }: { amount: number; kind: string }) {
  const icon = kind === 'gems' ? '💎' : kind === 'event_tokens' ? '🎟️' : '🔷';
  return (
    <span className="currency" title={kind}>
      <span aria-hidden="true">{icon}</span> {amount.toLocaleString()}
    </span>
  );
}

export function useToggle(initial = false): [boolean, () => void, (v: boolean) => void] {
  const [v, setV] = useState(initial);
  return [v, () => setV((x) => !x), setV];
}

export function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  const s = Math.max(1, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  const d = Math.floor(s / 86400);
  return d < 7 ? `${d}d` : new Date(iso).toLocaleDateString();
}

export function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString();
}
