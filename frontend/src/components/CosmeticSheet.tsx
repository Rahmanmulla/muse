import { useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { CosmeticThumb, ErrorState, Loading, Modal, RarityBadge } from './ui';
import { prettyCategory, type Cosmetic } from '../types';

// Cosmetic discovery: tapping a visible cosmetic (bubble in chat, frame/avatar
// on a profile) opens this lightweight sheet — name, rarity, collection,
// acquisition route, and provenance ("How did you get this?"). Deliberately
// minimal: discovery, not an ad.
export function CosmeticSheet({ cosmeticId, onClose }: { cosmeticId: string; onClose: () => void }) {
  const [item, setItem] = useState<Cosmetic | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // GET /catalog/{id} returns entitlement + favorite + status for owned items.
        const c = await api.get<Cosmetic>(`/catalog/${encodeURIComponent(cosmeticId)}`);
        if (!cancelled) setItem(c);
      } catch (e) {
        if (!cancelled) setErr(apiErrorMessage(e));
      }
    })();
    return () => { cancelled = true; };
  }, [cosmeticId]);

  return (
    <Modal title="Cosmetic" onClose={onClose}>
      {err ? <ErrorState message={err} /> :
        !item ? <Loading label="Loading cosmetic…" /> : (
          <div>
            <div className="row" style={{ marginBottom: 12 }}>
              <CosmeticThumb cosmetic={item} size={72} />
              <div>
                <div style={{ fontSize: 17, fontWeight: 800 }}>{item.name}</div>
                <div style={{ marginTop: 4 }}><RarityBadge rarity={item.rarity} /></div>
                <div className="muted small" style={{ marginTop: 4 }}>{prettyCategory(item.category)}</div>
              </div>
            </div>
            {item.description && <p className="muted" style={{ fontSize: 14 }}>{item.description}</p>}
            <div className="kv"><span className="muted">Collection</span><strong>{item.set_id ?? '—'}</strong></div>
            <div className="kv"><span className="muted">How to get it</span><strong>{acquisitionLabel(item)}</strong></div>
            <div className="kv"><span className="muted">You own it</span><strong>{item.owned ? 'Yes ✨' : 'Not yet'}</strong></div>
            {item.owned && item.source && (
              <p className="small" style={{ marginTop: 10, color: 'var(--muted)' }}>
                🕰️ <em>How did you get this?</em> — via <strong>{item.source.replace(/_/g, ' ')}</strong>
                {item.granted_at ? ` on ${new Date(item.granted_at).toLocaleDateString()}` : ''}.
              </p>
            )}
            {item.status && item.status !== 'live' && (
              <p className="small" style={{ color: 'var(--bad)' }}>Status: {item.status} (not in shop)</p>
            )}
            <p className="muted small" style={{ marginTop: 12 }}>
              Cosmetics are style only — zero gameplay advantage. ✨
            </p>
          </div>
        )}
    </Modal>
  );
}

function acquisitionLabel(c: Cosmetic): string {
  switch (c.acquisition) {
    case 'free': return 'Free claim';
    case 'purchase': return c.price_shards > 0 ? `Shop · ${c.price_shards} 🔷` : c.price_gems > 0 ? `Shop · ${c.price_gems} 💎` : 'Shop';
    case 'reward': return 'Reward / achievement';
    case 'event': return 'Event';
    case 'starter': return 'Starter kit';
    case 'referral': return 'Referral';
    default: return c.acquisition || '—';
  }
}
