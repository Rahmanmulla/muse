import { useCallback, useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { Empty, ErrorState, Loading, Modal, Avatar, timeAgo } from '../components/ui';
import type { Conversation, Message, Profile, WSFrame } from '../types';

function lastPreview(m?: Message | null): string {
  if (!m) return 'Say hello ✨';
  if (m.deleted) return 'Message deleted';
  if (m.kind !== 'text') return `Sent ${m.kind === 'sticker' ? 'a sticker' : 'an attachment'}`;
  return m.body ?? '';
}

export function Chats({ refreshKey, onOpen }: { refreshKey: number; onOpen: (id: number) => void }) {
  const { ws, toast, me, requestsCount } = useApp();
  const [convos, setConvos] = useState<Conversation[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const [newOpen, setNewOpen] = useState(false);
  const [online, setOnline] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    setErr(null);
    try {
      const c = await api.get<Conversation[]>('/conversations');
      setConvos(c);
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, []);

  useEffect(() => { load(); }, [load, refreshKey]);

  // realtime: new messages bump the list; presence updates dots
  useEffect(() => {
    return ws.on((f: WSFrame) => {
      try {
        if (f.type === 'message.new') {
          load();
        } else if (f.type === 'presence.changed') {
          const uid = f.user_id as number;
          setOnline((s) => {
            const n = new Set(s);
            if (f.online) n.add(uid); else n.delete(uid);
            return n;
          });
        } else if (f.type === 'message.read' || f.type === 'read.updated') {
          load();
        }
      } catch { /* ignore */ }
    });
  }, [ws, load]);

  const otherOf = (c: Conversation): Profile | undefined =>
    c.members.find((m) => m.id !== me?.id);

  const filtered = (convos ?? []).filter((c) => {
    if (!q.trim()) return true;
    const o = otherOf(c);
    const hay = `${o?.display_name ?? ''} ${o?.username ?? ''} ${c.title ?? ''}`.toLowerCase();
    return hay.includes(q.trim().toLowerCase());
  });

  return (
    <div>
      <div className="topbar">
        <h1><span className="brand">STIP</span></h1>
        <div className="grow" />
        <button className="icon-btn" style={{ position: 'relative' }}
          onClick={() => { window.location.hash = '#/requests'; }} aria-label="Message requests">
          📥
          {requestsCount > 0 && <span className="nav-badge">{requestsCount}</span>}
        </button>
        <button className="icon-btn" onClick={() => setNewOpen(true)} aria-label="New chat">✏️</button>
      </div>
      <div className="screen" style={{ paddingTop: 6 }}>
        <input
          className="input" placeholder="Search chats…" value={q}
          onChange={(e) => setQ(e.target.value)} aria-label="Search chats"
          style={{ marginBottom: 10 }}
        />
        {err ? (
          <ErrorState message={err} onRetry={load} />
        ) : convos === null ? (
          <Loading label="Loading chats…" />
        ) : filtered.length === 0 ? (
          <Empty
            icon="💬"
            title={q ? 'No chats match' : 'No chats yet'}
            hint={q ? 'Try a different search.' : 'Start a conversation and make it yours.'}
            action={!q ? <button className="btn" onClick={() => setNewOpen(true)}>New chat</button> : undefined}
          />
        ) : (
          filtered.map((c) => {
            const o = otherOf(c);
            return (
              <div key={c.id} className="card clickable chat-row" onClick={() => onOpen(c.id)} role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') onOpen(c.id); }}>
                <Avatar profile={o} size={48} />
                <div className="meta">
                  <div className="name">
                    {c.is_group ? (c.title ?? 'Group') : (o?.display_name ?? o?.username ?? '?')}
                    {o && <span className={'presence-dot' + (online.has(o.id) ? ' on' : '')} title={online.has(o.id) ? 'Online' : 'Offline'} />}
                  </div>
                  <div className="preview">{lastPreview(c.last_message)}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  {c.last_message && <div className="time">{timeAgo(c.last_message.created_at)}</div>}
                  {c.unread_count > 0 && <div style={{ marginTop: 4 }}><span className="unread-badge">{c.unread_count}</span></div>}
                </div>
              </div>
            );
          })
        )}
      </div>
      {newOpen && <NewChatModal onClose={() => setNewOpen(false)} onCreated={(id) => { setNewOpen(false); onOpen(id); }} toast={toast} />}
    </div>
  );
}

function NewChatModal({ onClose, onCreated, toast }: {
  onClose: () => void; onCreated: (id: number) => void; toast: (t: string) => void;
}) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Profile[]>([]);
  const [busy, setBusy] = useState(false);
  const [codeInput, setCodeInput] = useState('');

  useEffect(() => {
    if (!q.trim()) { setResults([]); return; }
    const t = window.setTimeout(async () => {
      try {
        const r = await api.get<Profile[]>(`/users/search?q=${encodeURIComponent(q.trim())}`);
        setResults(r);
      } catch { /* ignore */ }
    }, 300);
    return () => window.clearTimeout(t);
  }, [q]);

  const start = async (u: Profile) => {
    setBusy(true);
    try {
      const c = await api.post<Conversation>('/conversations', { user_id: u.id });
      onCreated(c.id);
    } catch {
      // Strangers are gated behind message requests — send one instead.
      try {
        const r = await api.post<{ direct: boolean; conversation_id?: number; request?: { id: number } }>(
          '/requests', { user_id: u.id, body: `Hi ${u.display_name}! 👋` });
        if (r.direct && r.conversation_id) onCreated(r.conversation_id);
        else { toast('📥 Message request sent — they\'ll see it when they accept.'); onClose(); }
      } catch (e) {
        toast(apiErrorMessage(e));
        setBusy(false);
      }
    }
  };

  const addByCode = async () => {
    const raw = codeInput.trim();
    const username = raw.startsWith('STIP:') ? raw.slice(5).trim() : raw;
    if (!username) return;
    setBusy(true);
    try {
      const r = await api.post<{ direct: boolean; conversation_id?: number; request?: { id: number } }>(
        '/requests', { username, body: 'Hi! 👋 Found you via your share code.' });
      if (r.direct && r.conversation_id) onCreated(r.conversation_id);
      else { toast('📥 Message request sent — they\'ll see it when they accept.'); onClose(); }
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="New chat" onClose={onClose}>
      <input className="input" placeholder="Search by username…" value={q}
        onChange={(e) => setQ(e.target.value)} autoFocus aria-label="Search users" />
      <div className="search-results" style={{ marginTop: 10 }}>
        {results.map((u) => (
          <div key={u.id} className="list-row">
            <Avatar profile={u} size={40} />
            <div className="grow">
              <div style={{ fontWeight: 600 }}>{u.display_name}</div>
              <div className="muted small">@{u.username}</div>
            </div>
            <button className="btn small" disabled={busy} onClick={() => start(u)}>Chat</button>
          </div>
        ))}
        {q.trim() && results.length === 0 && (
          <p className="muted small" style={{ textAlign: 'center', padding: 12 }}>No users found.</p>
        )}
      </div>
      <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--line)' }}>
        <label className="field">
          <span>📱 Add by code (from their Profile → Share)</span>
          <div className="row" style={{ gap: 8 }}>
            <input className="input grow" value={codeInput} onChange={(e) => setCodeInput(e.target.value)}
              placeholder="STIP:username" aria-label="Add by code" />
            <button className="btn small" disabled={busy || !codeInput.trim()} onClick={addByCode}>Add</button>
          </div>
        </label>
      </div>
    </Modal>
  );
}
