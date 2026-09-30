import { useCallback, useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { CosmeticThumb, Empty, ErrorBoundary, ErrorState, Loading, Modal, ProgressBar, RarityBadge, useToggle } from '../components/ui';
import { LOADOUT_SLOTS, RARITY_ORDER, SLOT_CATEGORY_MAP, SLOT_LABELS, prettyCategory, type CollectionBook, type Cosmetic, type Loadout, type LoadoutItem } from '../types';

export function Collection() {
  const { toast } = useApp();
  const [book, setBook] = useState<CollectionBook | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cat, setCat] = useState('all');
  const [rar, setRar] = useState('all');
  const [onlyFav, setOnlyFav] = useState(false);
  const [selected, setSelected] = useState<Cosmetic | null>(null);
  const [setsOpen, , setSetsOpen] = useToggle(false);
  const [loadoutsOpen, , setLoadoutsOpen] = useToggle(false);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const b = await api.get<CollectionBook>('/collection');
      setBook(b);
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const cats = ['all', ...new Set((book?.items ?? []).map((i) => i.category))];
  const items = (book?.items ?? []).filter(
    (i) => (cat === 'all' || i.category === cat) && (rar === 'all' || i.rarity === rar) && (!onlyFav || i.favorite)
  );

  const toggleFav = async (c: Cosmetic) => {
    try {
      if (c.favorite) await api.del(`/favorites/${c.id}`);
      else await api.post(`/favorites/${c.id}`, {});
      setBook((b) => b ? { ...b, items: b.items.map((i) => i.id === c.id ? { ...i, favorite: !c.favorite } : i) } : b);
      setSelected((s) => s && s.id === c.id ? { ...s, favorite: !c.favorite } : s);
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  return (
    <div>
      <div className="topbar">
        <h1>🎒 Collection</h1>
        <div className="grow" />
        <button className="btn small secondary" onClick={() => setLoadoutsOpen(true)}>Loadouts</button>
      </div>
      <div className="screen">
        {err ? <ErrorState message={err} onRetry={load} /> :
          book === null ? <Loading label="Opening collection…" /> : (
            <>
              <div className="card">
                <div className="row">
                  <div className="grow">
                    <strong>{book.owned_count}</strong> <span className="muted">/ {book.total} collected</span>
                    <ProgressBar value={book.owned_count} max={book.total} label="Collection progress" />
                  </div>
                  <button className="btn small secondary" onClick={() => setSetsOpen(true)}>
                    Sets ({book.sets.filter((s) => s.complete).length}/{book.sets.length})
                  </button>
                </div>
              </div>

              <div className="filter-row">
                {cats.map((c) => (
                  <button key={c} className={'chip' + (cat === c ? ' active' : '')} onClick={() => setCat(c)}>
                    {c === 'all' ? 'All' : prettyCategory(c)}
                  </button>
                ))}
              </div>
              <div className="filter-row">
                {['all', ...RARITY_ORDER].map((r) => (
                  <button key={r} className={'chip' + (rar === r ? ' active' : '')} onClick={() => setRar(r)}>{r}</button>
                ))}
                <button className={'chip' + (onlyFav ? ' active' : '')} onClick={() => setOnlyFav((v) => !v)}>⭐ Favorites</button>
              </div>

              {items.length === 0 ? (
                <Empty icon="🗂️" title="Nothing here" hint="Adjust filters, or visit the shop for new cosmetics." />
              ) : (
                <div className="grid">
                  {items.map((c) => (
                    <ErrorBoundary key={c.id} fallback={<div className="cos-card"><span>✨</span><span className="nm">{c.name}</span></div>}>
                      <div className="cos-card" onClick={() => setSelected(c)} role="button" tabIndex={0}
                        onKeyDown={(e) => { if (e.key === 'Enter') setSelected(c); }}>
                        <CosmeticThumb cosmetic={c} size={52} />
                        <span className="nm">{c.name}</span>
                        <RarityBadge rarity={c.rarity} />
                        {c.favorite && <span aria-label="favorite">⭐</span>}
                      </div>
                    </ErrorBoundary>
                  ))}
                </div>
              )}
            </>
          )}
      </div>

      {selected && (
        <Modal title={selected.name} onClose={() => setSelected(null)}>
          <div className="row" style={{ marginBottom: 12 }}>
            <CosmeticThumb cosmetic={selected} size={72} />
            <div>
              <RarityBadge rarity={selected.rarity} />
              <div className="muted small" style={{ marginTop: 4 }}>{prettyCategory(selected.category)} · from {selected.source ?? 'unknown'}</div>
            </div>
          </div>
          <p>{selected.description}</p>
          <div className="row wrap" style={{ gap: 8 }}>
            <button className="btn small secondary" onClick={() => toggleFav(selected)}>
              {selected.favorite ? '★ Unfavorite' : '☆ Favorite'}
            </button>
            <button className="btn small secondary" onClick={() => setLoadoutsOpen(true)}>Equip in loadout</button>
          </div>
        </Modal>
      )}

      {setsOpen && book && (
        <Modal title="Cosmetic sets" onClose={() => setSetsOpen(false)}>
          {book.sets.length === 0 && <p className="muted">No sets yet.</p>}
          {book.sets.map((s) => (
            <div key={s.id} className="card">
              <div className="row">
                <div className="grow">
                  <strong>{s.name}</strong>
                  <div className="muted small">{s.owned}/{s.total} owned {s.complete && '· ✅ Complete'}</div>
                  <ProgressBar value={s.owned} max={s.total} label={`${s.name} completion`} />
                </div>
              </div>
              <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
                {s.items.map((i) => (
                  <span key={i.id} title={`${i.name} (${i.rarity})`} style={{ fontSize: 22, opacity: i.owned ? 1 : 0.3 }}>
                    {i.asset?.emoji ?? '✨'}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </Modal>
      )}

      {loadoutsOpen && <LoadoutsModal onClose={() => setLoadoutsOpen(false)} />}
    </div>
  );
}

function LoadoutsModal({ onClose }: { onClose: () => void }) {
  const { toast } = useApp();
  const [loadouts, setLoadouts] = useState<Loadout[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [inventory, setInventory] = useState<Cosmetic[] | null>(null);
  const [pickFor, setPickFor] = useState<{ loadoutId: number; slot: string } | null>(null);
  const [newName, setNewName] = useState('');

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [l, inv] = await Promise.all([
        api.get<Loadout[]>('/loadouts'),
        api.get<Cosmetic[]>('/inventory'),
      ]);
      setLoadouts(l);
      setInventory(inv);
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    try {
      await api.post('/loadouts', { name: newName.trim() || undefined });
      setNewName('');
      load();
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const activate = async (id: number) => {
    try {
      await api.post(`/loadouts/${id}/activate`, {});
      toast('✨ Loadout activated');
      load();
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const equip = async (loadoutId: number, slot: string, cosmeticId: string | null) => {
    try {
      await api.put(`/loadouts/${loadoutId}`, { slot, cosmetic_id: cosmeticId });
      setPickFor(null);
      load();
    } catch (e) {
      // 403 ownership errors surface here, verbatim from the server
      toast(apiErrorMessage(e));
    }
  };

  const remove = async (id: number) => {
    if (!window.confirm('Delete this loadout?')) return;
    try {
      await api.del(`/loadouts/${id}`);
      load();
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  // inventory filtered to the slot's allowed categories (backend SLOT_CATEGORY_MAP)
  const candidates = pickFor && inventory
    ? inventory.filter((c) => (SLOT_CATEGORY_MAP[pickFor.slot] ?? []).includes(c.category))
    : [];

  // show every valid slot in canonical order, plus any extra keys the server returned
  const slotsFor = (l: Loadout): string[] => {
    const extra = Object.keys(l.items ?? {}).filter((k) => !(LOADOUT_SLOTS as readonly string[]).includes(k));
    return [...LOADOUT_SLOTS, ...extra];
  };

  return (
    <Modal title="Loadouts" onClose={onClose}>
      {err ? <ErrorState message={err} onRetry={load} /> :
        loadouts === null ? <Loading label="Loading loadouts…" /> : (
          <>
            <div className="row" style={{ marginBottom: 12 }}>
              <input className="input" placeholder="New loadout name…" value={newName}
                onChange={(e) => setNewName(e.target.value)} aria-label="New loadout name" />
              <button className="btn small" onClick={create}>Create</button>
            </div>
            {loadouts.length === 0 && <Empty icon="👗" title="No loadouts" hint="Create one to mix and match your cosmetics." />}
            {loadouts.map((l) => (
              <div key={l.id} className="card">
                <div className="row">
                  <strong className="grow">{l.name} {l.is_active && <span className="muted small">· active</span>}</strong>
                  {!l.is_active && <button className="btn small" onClick={() => activate(l.id)}>Activate</button>}
                  <button className="icon-btn" onClick={() => remove(l.id)} aria-label={`Delete ${l.name}`}>🗑️</button>
                </div>
                <div style={{ marginTop: 10 }}>
                  {slotsFor(l).map((slot) => {
                    const item: LoadoutItem | null = l.items[slot] ?? null;
                    return (
                      <div key={slot} className="list-row">
                        <span className="muted small" style={{ width: 110 }}>{SLOT_LABELS[slot] ?? slot}</span>
                        <span className="grow">{item ? `${item.asset?.emoji ?? '✨'} ${item.name}` : <em className="muted">empty</em>}</span>
                        <button className="btn small secondary" onClick={() => setPickFor({ loadoutId: l.id, slot })}>
                          {item ? 'Change' : 'Equip'}
                        </button>
                        {item && <button className="icon-btn" onClick={() => equip(l.id, slot, null)} aria-label="Unequip">✕</button>}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </>
        )}

      {pickFor && (
        <Modal title={`Equip ${SLOT_LABELS[pickFor.slot] ?? pickFor.slot}`} onClose={() => setPickFor(null)}>
          {candidates.length === 0 ? (
            <Empty icon="🎒" title="Nothing to equip" hint={`You don't own any ${(SLOT_LABELS[pickFor.slot] ?? pickFor.slot).toLowerCase()} cosmetics yet. Check the shop.`} />
          ) : (
            <div className="grid">
              {candidates.map((c) => (
                <div key={c.id} className="cos-card" onClick={() => equip(pickFor.loadoutId, pickFor.slot, c.id)} role="button" tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') equip(pickFor.loadoutId, pickFor.slot, c.id); }}>
                  <CosmeticThumb cosmetic={c} size={48} />
                  <span className="nm">{c.name}</span>
                  <RarityBadge rarity={c.rarity} />
                </div>
              ))}
            </div>
          )}
        </Modal>
      )}
    </Modal>
  );
}
