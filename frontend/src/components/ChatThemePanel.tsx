import { useCallback, useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { CosmeticThumb, Loading, Modal } from './ui';
import type { ChatTheme, CollectionBook, Cosmetic } from '../types';

// Chat personality panel: per-conversation wallpaper + bubble, personal or
// shared scope. Ownership is enforced server-side.
export function ChatThemePanel({ convId, onClose, onChanged }: {
  convId: number; onClose: () => void; onChanged: () => void;
}) {
  const { toast } = useApp();
  const [theme, setTheme] = useState<ChatTheme | null>(null);
  const [walls, setWalls] = useState<Cosmetic[]>([]);
  const [bubbles, setBubbles] = useState<Cosmetic[]>([]);
  const [selWall, setSelWall] = useState<string | null>(null);
  const [selBubble, setSelBubble] = useState<string | null>(null);
  const [scope, setScope] = useState<'personal' | 'shared'>('personal');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const [t, book] = await Promise.all([
        api.get<ChatTheme>(`/conversations/${convId}/theme`).catch(() => null),
        api.get<CollectionBook>('/collection').catch(() => null),
      ]);
      setTheme(t);
      const wallVal = t?.wallpaper_id as unknown;
      const bubVal = t?.bubble_id as unknown;
      setSelWall(typeof wallVal === 'object' && wallVal !== null ? ((wallVal as Cosmetic).id ?? null) : (wallVal as string | null) ?? null);
      setSelBubble(typeof bubVal === 'object' && bubVal !== null ? ((bubVal as Cosmetic).id ?? null) : (bubVal as string | null) ?? null);
      setScope((t?.scope as 'personal' | 'shared') || 'personal');
      if (book) {
        setWalls(book.items.filter((i) => i.owned && i.category === 'chat.wallpaper'));
        setBubbles(book.items.filter((i) => i.owned && i.category === 'chat.bubble'));
      }
    } finally {
      setLoaded(true);
    }
  }, [convId]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/conversations/${convId}/theme`, {
        scope,
        wallpaper_id: selWall,
        bubble_id: selBubble,
      });
      toast('🎨 Chat theme saved');
      onChanged();
      onClose();
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (!window.confirm('Reset this chat to your default style?')) return;
    setBusy(true);
    try {
      await api.del(`/conversations/${convId}/theme`);
      toast('Theme reset');
      onChanged();
      onClose();
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="🎨 Chat personality" onClose={onClose}>
      {!loaded ? <Loading label="Loading theme…" /> : (
        <>
          <div className="auth-tabs" role="tablist" aria-label="Theme scope">
            <button type="button" className={'btn small' + (scope === 'personal' ? '' : ' secondary')}
              onClick={() => setScope('personal')}>👁️ Personal</button>
            <button type="button" className={'btn small' + (scope === 'shared' ? '' : ' secondary')}
              onClick={() => setScope('shared')}>👥 Shared</button>
          </div>
          <p className="muted small">
            {scope === 'personal'
              ? 'Only you see this style.'
              : 'Both of you see this style (shared).'}
          </p>

          <h4>Wallpaper</h4>
          {walls.length === 0 ? <p className="muted small">No wallpapers owned yet — check the Shop.</p> : (
            <div className="grid">
              {walls.map((c) => (
                <div key={c.id} className="cos-card" onClick={() => setSelWall(selWall === c.id ? null : c.id)}
                  role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setSelWall(selWall === c.id ? null : c.id); }}
                  style={selWall === c.id ? { borderColor: 'var(--accent)' } : undefined}>
                  <CosmeticThumb cosmetic={c} size={52} />
                  <span className="nm">{c.name}</span>
                </div>
              ))}
            </div>
          )}

          <h4 style={{ marginTop: 14 }}>Bubble</h4>
          {bubbles.length === 0 ? <p className="muted small">No bubbles owned yet — check the Shop.</p> : (
            <div className="grid">
              {bubbles.map((c) => (
                <div key={c.id} className="cos-card" onClick={() => setSelBubble(selBubble === c.id ? null : c.id)}
                  role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') setSelBubble(selBubble === c.id ? null : c.id); }}
                  style={selBubble === c.id ? { borderColor: 'var(--accent)' } : undefined}>
                  <CosmeticThumb cosmetic={c} size={52} />
                  <span className="nm">{c.name}</span>
                </div>
              ))}
            </div>
          )}

          <div className="row" style={{ marginTop: 16, gap: 8 }}>
            <button className="btn grow" disabled={busy} onClick={save}>{busy ? '…' : 'Save theme'}</button>
            {theme && (theme.wallpaper_id || theme.bubble_id) && (
              <button className="btn secondary" disabled={busy} onClick={clear}>Reset</button>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}
