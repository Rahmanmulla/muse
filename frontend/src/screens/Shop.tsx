import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, apiErrorMessage, uuid } from '../api';
import { useApp } from '../store';
import { CosmeticThumb, Currency, Empty, ErrorBoundary, ErrorState, Loading, Modal, RarityBadge, SectionTitle, useToggle } from '../components/ui';
import { RARITY_ORDER, type Bundle, type DailyClaim, type DailyStatus, type GiftTx, type PurchaseResult, type Shop, type ShopItem } from '../types';

export function Shop() {
  const { balances, refreshWallet, toast } = useApp();
  const [shop, setShop] = useState<Shop | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [buying, setBuying] = useState<ShopItem | null>(null);
  const [bundleBuying, setBundleBuying] = useState<Bundle | null>(null);
  const [giftFor, setGiftFor] = useState<{ kind: 'cosmetic' | 'bundle'; id: string; name: string } | null>(null);
  const [dailyOpen, , setDailyOpen] = useToggle(false);
  const [giftsOpen, , setGiftsOpen] = useToggle(false);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const s = await api.get<Shop>('/shop');
      setShop(s);
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const purchase = async (itemType: 'cosmetic' | 'bundle' | 'currency_pack', itemId: string, recipientId?: number) => {
    try {
      const r = await api.post<PurchaseResult>('/shop/purchase', {
        item_type: itemType, item_id: itemId, idempotency_key: uuid(), recipient_id: recipientId,
      });
      if (r.duplicate) toast('♻️ Already processed — no double charge.');
      else toast(recipientId ? '🎁 Gift sent!' : '🛍️ Purchase complete!');
      refreshWallet();
      load();
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  return (
    <div>
      <div className="topbar">
        <h1>🛍️ Shop</h1>
        <div className="grow" />
        <button className="btn small secondary" onClick={() => setDailyOpen(true)}>🎁 Daily</button>
      </div>
      <div className="wallet-bar">
        <Currency amount={balances.shards ?? 0} kind="shards" />
        <Currency amount={balances.gems ?? 0} kind="gems" />
        <Currency amount={balances.event_tokens ?? 0} kind="event_tokens" />
        <div className="grow" />
        <button className="btn small secondary" onClick={() => setGiftsOpen(true)}>Gifts</button>
      </div>
      <div className="screen" style={{ paddingTop: 0 }}>
        {err ? <ErrorState message={err} onRetry={load} /> :
          shop === null ? <Loading label="Stocking the shop…" /> : (
            <>
              {shop.featured.length > 0 && (
                <>
                  <SectionTitle>✨ Featured</SectionTitle>
                  <div className="shop-carousel">
                    {shop.featured.map((i) => (
                      <ErrorBoundary key={i.id} fallback={<div className="cos-card"><span>✨</span></div>}>
                        <ShopCard item={i} onBuy={() => setBuying(i)}
                          onGift={() => setGiftFor({ kind: 'cosmetic', id: i.id, name: i.name })} />
                      </ErrorBoundary>
                    ))}
                  </div>
                </>
              )}

              {shop.free.length > 0 && (
                <>
                  <SectionTitle>🆓 Free</SectionTitle>
                  <div className="grid">
                    {shop.free.map((i) => (
                      <ShopCard key={i.id} item={i} onBuy={() => purchase('cosmetic', i.id)}
                        onGift={() => setGiftFor({ kind: 'cosmetic', id: i.id, name: i.name })} free />
                    ))}
                  </div>
                </>
              )}

              {RARITY_ORDER.map((r) => {
                const items = shop.by_rarity[r] ?? [];
                if (!items.length) return null;
                return (
                  <div key={r}>
                    <SectionTitle><RarityBadge rarity={r} /></SectionTitle>
                    <div className="grid">
                      {items.map((i) => (
                        <ShopCard key={i.id} item={i} onBuy={() => setBuying(i)}
                          onGift={() => setGiftFor({ kind: 'cosmetic', id: i.id, name: i.name })} />
                      ))}
                    </div>
                  </div>
                );
              })}

              {shop.bundles.length > 0 && (
                <>
                  <SectionTitle>📦 Bundles</SectionTitle>
                  {shop.bundles.map((b) => (
                    <div key={b.id} className="card">
                      <div className="row">
                        <div className="grow">
                          <strong>{b.name}</strong>
                          <div className="muted small">{b.description}</div>
                          <div className="muted small">{b.cosmetic_ids.length} items</div>
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <Price shards={b.price_shards} gems={b.price_gems} />
                          <div className="row" style={{ marginTop: 6, justifyContent: 'flex-end' }}>
                            <button className="btn small" onClick={() => setBundleBuying(b)}>Buy</button>
                            <button className="btn small secondary" onClick={() => setGiftFor({ kind: 'bundle', id: b.id, name: b.name })}>Gift</button>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </>
              )}

              {shop.currency_packs.length > 0 && (
                <>
                  <SectionTitle>💎 Currency packs</SectionTitle>
                  <p className="muted small">Dev provider — no real billing happens.</p>
                  {shop.currency_packs.map((p) => (
                    <div key={p.id} className="card">
                      <div className="row">
                        <div className="grow"><strong>{p.name}</strong><div className="muted small">{p.gems} 💎</div></div>
                        <button className="btn small" onClick={() => purchase('currency_pack', p.id)}>Get</button>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </>
          )}
      </div>

      {buying && (
        <BuyModal
          title={buying.name} onClose={() => setBuying(null)}
          onConfirm={(recipientId) => { setBuying(null); purchase('cosmetic', buying.id, recipientId); }}
          price={<Price shards={buying.price_shards} gems={buying.price_gems} />}
          preview={<CosmeticThumb cosmetic={buying} size={72} />}
        />
      )}
      {bundleBuying && (
        <BuyModal
          title={bundleBuying.name} onClose={() => setBundleBuying(null)}
          onConfirm={(recipientId) => { setBundleBuying(null); purchase('bundle', bundleBuying.id, recipientId); }}
          price={<Price shards={bundleBuying.price_shards} gems={bundleBuying.price_gems} />}
          preview={<span style={{ fontSize: 48 }}>📦</span>}
        />
      )}
      {giftFor && <GiftModal item={giftFor} onClose={() => setGiftFor(null)}
        onConfirm={(uid) => { const g = giftFor; setGiftFor(null); purchase(g.kind === 'cosmetic' ? 'cosmetic' : 'bundle', g.id, uid); }} />}
      {dailyOpen && <DailyModal onClose={() => setDailyOpen(false)} />}
      {giftsOpen && <GiftsModal onClose={() => setGiftsOpen(false)} />}
    </div>
  );
}

export function Price({ shards, gems }: { shards: number; gems: number }) {
  return (
    <div className="row" style={{ gap: 10 }}>
      {shards > 0 && <Currency amount={shards} kind="shards" />}
      {gems > 0 && <Currency amount={gems} kind="gems" />}
      {shards === 0 && gems === 0 && <span className="muted">Free</span>}
    </div>
  );
}

function ShopCard({ item, onBuy, onGift, free }: {
  item: ShopItem; onBuy: () => void; onGift: () => void; free?: boolean;
}) {
  return (
    <div className="cos-card">
      <CosmeticThumb cosmetic={item} size={52} />
      <span className="nm">{item.name}</span>
      <RarityBadge rarity={item.rarity} />
      {free ? <span className="muted small">Free</span> : <Price shards={item.price_shards} gems={item.price_gems} />}
      <div className="row" style={{ gap: 4 }}>
        <button className="btn small" onClick={onBuy}>{free ? 'Claim' : 'Buy'}</button>
        <button className="btn small secondary" onClick={onGift} title="Buy as gift">🎁</button>
      </div>
    </div>
  );
}

function BuyModal({ title, preview, price, onClose, onConfirm }: {
  title: string; preview: ReactNode; price: ReactNode;
  onClose: () => void; onConfirm: (recipientId?: number) => void;
}) {
  const { toast } = useApp();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<{ id: number; username: string; display_name: string }[]>([]);
  const [recipient, setRecipient] = useState<number | null>(null);

  useEffect(() => {
    if (!q.trim()) { setResults([]); return; }
    const t = window.setTimeout(async () => {
      try {
        const r = await api.get<{ id: number; username: string; display_name: string }[]>(`/users/search?q=${encodeURIComponent(q.trim())}`);
        setResults(r);
      } catch (e) { toast(apiErrorMessage(e)); }
    }, 300);
    return () => window.clearTimeout(t);
  }, [q, toast]);

  return (
    <Modal title={title} onClose={onClose}>
      <div style={{ textAlign: 'center', marginBottom: 12 }}>{preview}</div>
      <div className="row" style={{ justifyContent: 'center', marginBottom: 16 }}>{price}</div>
      <label className="field">
        <span>Gift to a friend (optional)</span>
        <input className="input" placeholder="Search username…" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      {results.map((u) => (
        <div key={u.id} className="list-row">
          <span className="grow">{u.display_name} <span className="muted">@{u.username}</span></span>
          <button className={'btn small' + (recipient === u.id ? '' : ' secondary')} onClick={() => setRecipient(recipient === u.id ? null : u.id)}>
            {recipient === u.id ? '✓ Selected' : 'Select'}
          </button>
        </div>
      ))}
      <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
        <button className="btn secondary" onClick={onClose}>Cancel</button>
        <button className="btn" onClick={() => onConfirm(recipient ?? undefined)}>
          {recipient ? '🎁 Buy gift' : 'Confirm purchase'}
        </button>
      </div>
      <p className="muted small" style={{ marginTop: 10 }}>Protected by idempotency key — double-taps never double-charge.</p>
    </Modal>
  );
}

function GiftModal({ item, onClose, onConfirm }: {
  item: { kind: 'cosmetic' | 'bundle'; id: string; name: string };
  onClose: () => void; onConfirm: (uid: number) => void;
}) {
  const { toast } = useApp();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<{ id: number; username: string; display_name: string }[]>([]);

  useEffect(() => {
    if (!q.trim()) { setResults([]); return; }
    const t = window.setTimeout(async () => {
      try {
        const r = await api.get<{ id: number; username: string; display_name: string }[]>(`/users/search?q=${encodeURIComponent(q.trim())}`);
        setResults(r);
      } catch (e) { toast(apiErrorMessage(e)); }
    }, 300);
    return () => window.clearTimeout(t);
  }, [q, toast]);

  return (
    <Modal title={`Gift: ${item.name}`} onClose={onClose}>
      <input className="input" placeholder="Search friend's username…" value={q}
        onChange={(e) => setQ(e.target.value)} autoFocus aria-label="Search friend" />
      <div style={{ marginTop: 8 }}>
        {results.map((u) => (
          <div key={u.id} className="list-row">
            <span className="grow">{u.display_name} <span className="muted">@{u.username}</span></span>
            <button className="btn small" onClick={() => onConfirm(u.id)}>🎁 Send gift</button>
          </div>
        ))}
        {q.trim() && results.length === 0 && <p className="muted small" style={{ textAlign: 'center' }}>No users found.</p>}
      </div>
    </Modal>
  );
}

export function DailyModal({ onClose }: { onClose: () => void }) {
  const { toast, refreshWallet } = useApp();
  const [status, setStatus] = useState<DailyStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [claiming, setClaiming] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try {
      setStatus(await api.get<DailyStatus>('/rewards/daily'));
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const claim = async () => {
    setClaiming(true);
    try {
      const r = await api.post<DailyClaim>('/rewards/daily/claim', {});
      toast(`🎁 Day ${r.day_number} claimed! +${r.granted.shards} 🔷${r.granted.gems ? ` +${r.granted.gems} 💎` : ''}`);
      if (r.leveled_up) toast('🎉 Level up!');
      refreshWallet();
      load();
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setClaiming(false);
    }
  };

  return (
    <Modal title="Daily rewards" onClose={onClose}>
      {err ? <ErrorState message={err} onRetry={load} /> :
        status === null ? <Loading label="Loading rewards…" /> : (
          <>
            <p className="muted small">Come back every day — streaks unlock bigger rewards across the 30-day ladder.</p>
            <div className="ladder">
              {status.ladder.map((d) => {
                const isToday = d.day === status.next_day && !status.claimed;
                const claimed = d.day < status.next_day || (d.day === status.next_day && status.claimed);
                return (
                  <div key={d.day} className={'ladder-day' + (isToday ? ' today' : '') + (claimed ? ' claimed' : '')}>
                    <div className="d">Day {d.day}</div>
                    <div className="rw">{claimed ? '✅' : d.cosmetic_id ? '🎨' : d.gems ? '💎' : '🔷'}</div>
                    <div className="small muted">
                      {d.cosmetic_id ? 'style' : d.gems ? `${d.gems} 💎` : `${d.shards} 🔷`}
                    </div>
                  </div>
                );
              })}
            </div>
            <button className="btn" style={{ width: '100%', marginTop: 16 }} disabled={status.claimed || claiming} onClick={claim}>
              {status.claimed ? `✅ Claimed — come back tomorrow` : claiming ? 'Claiming…' : `Claim day ${status.next_day}`}
            </button>
          </>
        )}
    </Modal>
  );
}

function GiftsModal({ onClose }: { onClose: () => void }) {
  const { me } = useApp();
  const [gifts, setGifts] = useState<GiftTx[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<GiftTx[]>('/gifts').then(setGifts).catch((e) => setErr(apiErrorMessage(e)));
  }, []);

  return (
    <Modal title="Gift history" onClose={onClose}>
      {err ? <ErrorState message={err} onRetry={() => window.location.reload()} /> :
        gifts === null ? <Loading label="Loading gifts…" /> :
        gifts.length === 0 ? <Empty icon="🎁" title="No gifts yet" hint="Send a cosmetic from the shop to surprise a friend." /> :
        gifts.map((g) => (
          <div key={g.id} className="list-row">
            <span style={{ fontSize: 24 }}>🎁</span>
            <div className="grow">
              <div><strong>{g.cosmetic_id}</strong></div>
              <div className="muted small">{g.sender_id === me?.id ? 'You sent this' : 'You received this'} · {g.status}</div>
            </div>
            <span className="muted small">{new Date(g.created_at).toLocaleDateString()}</span>
          </div>
        ))}
    </Modal>
  );
}

export function GiftFromInventory({ cosmeticId, cosmeticName }: { cosmeticId: string; cosmeticName: string }) {
  const { toast } = useApp();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [results, setResults] = useState<{ id: number; username: string; display_name: string }[]>([]);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (!open || !q.trim()) { setResults([]); return; }
    const t = window.setTimeout(async () => {
      try {
        const r = await api.get<{ id: number; username: string; display_name: string }[]>(`/users/search?q=${encodeURIComponent(q.trim())}`);
        setResults(r);
      } catch (e) { toast(apiErrorMessage(e)); }
    }, 300);
    return () => window.clearTimeout(t);
  }, [q, open, toast]);

  const send = async (uid: number) => {
    try {
      await api.post('/gifts', { cosmetic_id: cosmeticId, recipient_id: uid, message: msg || undefined });
      toast('🎁 Gift sent!');
      setOpen(false);
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  return (
    <>
      <button className="btn small secondary" onClick={() => setOpen(true)}>🎁 Gift</button>
      {open && (
        <Modal title={`Gift ${cosmeticName}`} onClose={() => setOpen(false)}>
          <input className="input" placeholder="Friend's username…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
          <label className="field" style={{ marginTop: 10 }}>
            <span>Note (optional)</span>
            <input className="input" value={msg} onChange={(e) => setMsg(e.target.value)} maxLength={140} />
          </label>
          {results.map((u) => (
            <div key={u.id} className="list-row">
              <span className="grow">{u.display_name} <span className="muted">@{u.username}</span></span>
              <button className="btn small" onClick={() => send(u.id)}>Send</button>
            </div>
          ))}
          <p className="muted small">Transfers an owned, transferable cosmetic. This can't be undone.</p>
        </Modal>
      )}
    </>
  );
}
