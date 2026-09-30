import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { Avatar, Empty, ErrorBoundary, ErrorState, Loading, Modal, assetGradient, timeAgo } from '../components/ui';
import { CosmeticSheet } from '../components/CosmeticSheet';
import { ChatThemePanel } from '../components/ChatThemePanel';
import { LinkPreviewCard } from '../components/LinkPreview';
import type { ChatTheme, Conversation, Cosmetic, CosmeticAsset, Message, Profile, WSFrame } from '../types';

const EMOJIS = ['❤️', '😂', '😮', '😢', '🔥', '👍'];

function dayKey(iso: string): string {
  return new Date(iso).toDateString();
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yest = new Date();
  yest.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yest.toDateString()) return 'Yesterday';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export function ChatView({ convId, onBack }: { convId: number; onBack: () => void }) {
  const { me, ws, toast } = useApp();
  const [conv, setConv] = useState<Conversation | null>(null);
  const [msgs, setMsgs] = useState<Message[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [theme, setTheme] = useState<ChatTheme | null>(null);
  const [draft, setDraft] = useState('');
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [editing, setEditing] = useState<Message | null>(null);
  const [editText, setEditText] = useState('');
  const [typingUsers, setTypingUsers] = useState<Set<number>>(new Set());
  const [pins, setPins] = useState<Message[]>([]);
  const [showPins, setShowPins] = useState(false);
  const [searchQ, setSearchQ] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchRes, setSearchRes] = useState<Message[] | null>(null);
  const [reactFor, setReactFor] = useState<Message | null>(null);
  const [uploading, setUploading] = useState(false);
  const [streak, setStreak] = useState<number | null>(null);
  const [themeOpen, setThemeOpen] = useState(false);
  const [sheetCosmeticId, setSheetCosmeticId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const typingTimer = useRef<number | undefined>(undefined);
  const fileRef = useRef<HTMLInputElement>(null);

  const other: Profile | undefined = conv?.members.find((m) => m.id !== me?.id);

  const loadConv = useCallback(async () => {
    try {
      const cs = await api.get<Conversation[]>('/conversations');
      const c = cs.find((x) => x.id === convId) ?? null;
      setConv(c);
      if (c && !c.is_group) {
        const o = c.members.find((m) => m.id !== me?.id);
        if (o) {
          try {
            const s = await api.get<{ count: number }>(`/streaks/${o.id}`);
            setStreak(s.count);
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, [convId, me?.id]);

  const loadMsgs = useCallback(async () => {
    setErr(null);
    try {
      const m = await api.get<Message[]>(`/conversations/${convId}/messages?limit=60`);
      setMsgs([...m].reverse());
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, [convId]);

  const loadTheme = useCallback(async () => {
    try {
      const t = await api.get<ChatTheme>(`/conversations/${convId}/theme`);
      setTheme(t);
    } catch { /* theme is optional */ }
  }, [convId]);

  const loadPins = useCallback(async () => {
    try {
      const p = await api.get<Message[]>(`/conversations/${convId}/pins`);
      setPins(p);
    } catch { /* ignore */ }
  }, [convId]);

  const loadDraft = useCallback(async () => {
    try {
      const d = await api.get<{ body: string }>(`/conversations/${convId}/draft`);
      if (d?.body) setDraft(d.body);
    } catch { /* ignore */ }
  }, [convId]);

  useEffect(() => {
    loadConv(); loadMsgs(); loadTheme(); loadPins(); loadDraft();
  }, [loadConv, loadMsgs, loadTheme, loadPins, loadDraft]);

  // scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'auto' });
  }, [msgs?.length]);

  // mark read on new incoming messages
  useEffect(() => {
    const last = msgs && msgs.length ? msgs[msgs.length - 1] : null;
    if (last && last.sender_id !== me?.id) {
      api.post(`/conversations/${convId}/read`, { message_id: last.id }).catch(() => {});
    }
  }, [msgs, convId, me?.id]);

  // persist draft (debounced)
  useEffect(() => {
    const t = window.setTimeout(() => {
      api.put(`/conversations/${convId}/draft`, { body: draft }).catch(() => {});
    }, 1200);
    return () => window.clearTimeout(t);
  }, [draft, convId]);

  // realtime — real backend event types:
  // message.new {message, style}, message.edit {message},
  // message.delete {conversation_id, message_id}, message.read {conversation_id, user_id, last_message_id},
  // reaction.added/removed {message_id, emoji, user_id}, typing.started/stopped {conversation_id, user_id}
  // (legacy API.md aliases message.updated/message.deleted/typing/read.updated/reaction.updated kept as fallback)
  useEffect(() => {
    const applyMessage = (m: Message) =>
      setMsgs((ms) => {
        if (!ms) return ms;
        if (ms.some((x) => x.id === m.id)) return ms.map((x) => (x.id === m.id ? m : x));
        return [...ms, m];
      });
    const tombstone = (mid: number) =>
      setMsgs((ms) => (ms ?? []).map((x) => (x.id === mid ? { ...x, deleted: true, body: null } : x)));

    return ws.on((f: WSFrame) => {
      try {
        const cid = (f.conversation_id as number) ?? ((f.message as Message | undefined)?.conversation_id);
        if (cid !== convId) return;
        switch (f.type) {
          case 'message.new': {
            const m = f.message as Message;
            if (m) {
              applyMessage(m);
              if ((f as { leveled_up?: boolean }).leveled_up) toast('🎉 Level up!');
            }
            break;
          }
          case 'message.edit':
          case 'message.updated': {
            const m = f.message as Message;
            if (m) setMsgs((ms) => (ms ?? []).map((x) => (x.id === m.id ? m : x)));
            break;
          }
          case 'message.delete':
          case 'message.deleted':
            tombstone(f.message_id as number);
            break;
          case 'reaction.added':
          case 'reaction.removed':
          case 'reaction.updated': {
            // no single-message GET; refresh the page to pick up reaction state
            loadMsgs();
            break;
          }
          case 'typing.started':
          case 'typing.stopped':
          case 'typing': {
            const uid = f.user_id as number;
            if (uid === me?.id) break;
            const isTyping = f.type === 'typing.started' || (f.type === 'typing' && f.typing === true);
            setTypingUsers((s) => {
              const n = new Set(s);
              if (isTyping) n.add(uid); else n.delete(uid);
              return n;
            });
            if (isTyping) {
              window.setTimeout(() => setTypingUsers((s) => {
                const n = new Set(s); n.delete(uid); return n;
              }), 6000);
            }
            break;
          }
          case 'message.read':
          case 'read.updated':
            loadMsgs();
            break;
          default:
            break;
        }
      } catch { /* ignore */ }
    });
  }, [ws, convId, me?.id, toast, loadMsgs]);

  const sendTyping = (typing: boolean) => {
    api.post(`/conversations/${convId}/typing`, { typing }).catch(() => {});
  };

  const onInput = (v: string) => {
    setDraft(v);
    sendTyping(true);
    if (typingTimer.current) window.clearTimeout(typingTimer.current);
    typingTimer.current = window.setTimeout(() => sendTyping(false), 2500);
  };

  const send = async () => {
    const body = draft.trim();
    if (!body) return;
    setDraft('');
    setReplyTo(null);
    sendTyping(false);
    try {
      const m = await api.post<Message>(`/conversations/${convId}/messages`, {
        body, reply_to_id: replyTo?.id,
      });
      setMsgs((ms) => [...(ms ?? []), m]);
      if (m.leveled_up) toast('🎉 Level up!');
    } catch (e) {
      toast(apiErrorMessage(e));
      setDraft(body);
    }
  };

  const doEdit = async () => {
    if (!editing) return;
    try {
      const m = await api.patch<Message>(`/conversations/${convId}/messages/${editing.id}`, { body: editText.trim() });
      setMsgs((ms) => (ms ?? []).map((x) => (x.id === m.id ? m : x)));
      setEditing(null);
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const doDelete = async (m: Message) => {
    if (!window.confirm('Delete this message?')) return;
    try {
      await api.del(`/conversations/${convId}/messages/${m.id}`);
      setMsgs((ms) => (ms ?? []).map((x) => (x.id === m.id ? { ...x, deleted: true, body: null } : x)));
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const doReact = async (m: Message, emoji: string) => {
    try {
      const has = m.reactions.some((r) => r.emoji === emoji && r.users.includes(me?.id ?? -1));
      // Backend: DELETE takes ?emoji= query param and returns {ok:true}; POST returns {ok:true}.
      // Fresh reaction state arrives via reaction.added/removed WS events; reload as fallback.
      if (has) {
        await api.del(`/conversations/${convId}/messages/${m.id}/reactions?emoji=${encodeURIComponent(emoji)}`);
      } else {
        await api.post(`/conversations/${convId}/messages/${m.id}/reactions`, { emoji });
      }
      loadMsgs();
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setReactFor(null);
    }
  };

  const doPin = async (m: Message) => {
    try {
      await api.post(`/conversations/${convId}/messages/${m.id}/pin`, {});
      toast('📌 Pinned');
      loadPins();
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const doForward = async (m: Message) => {
    try {
      const cs = await api.get<Conversation[]>('/conversations');
      const targets = cs.filter((c) => c.id !== convId);
      if (!targets.length) { toast('No other chats to forward to.'); return; }
      const names = targets.map((c, i) => `${i + 1}. ${c.members.find((x) => x.id !== me?.id)?.display_name ?? c.title}`).join('\n');
      const pick = window.prompt(`Forward to:\n${names}`);
      const idx = pick ? parseInt(pick, 10) - 1 : -1;
      if (idx >= 0 && idx < targets.length) {
        await api.post(`/conversations/${convId}/messages/${m.id}/forward`, { target_conv_id: targets[idx].id });
        toast('↗️ Forwarded');
      }
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const doSearch = async () => {
    if (!searchQ.trim()) { setSearchRes(null); return; }
    setSearching(true);
    try {
      const r = await api.get<Message[]>(`/conversations/${convId}/search?q=${encodeURIComponent(searchQ.trim())}`);
      setSearchRes(r);
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setSearching(false);
    }
  };

  const upload = async (f: File) => {
    if (f.size > 10 * 1024 * 1024) { toast('File too large (10MB max).'); return; }
    setUploading(true);
    try {
      const u = await api.upload<{ media_path: string; media_mime: string; media_size: number }>('/media/upload', f);
      const kind = u.media_mime.startsWith('image/') ? 'image' : u.media_mime.startsWith('video/') ? 'video' : 'file';
      const m = await api.post<Message>(`/conversations/${convId}/messages`, {
        kind, media_path: u.media_path, media_mime: u.media_mime, media_size: u.media_size,
        body: kind === 'file' ? f.name : undefined,
      });
      setMsgs((ms) => [...(ms ?? []), m]);
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setUploading(false);
    }
  };

  const wallpaper = theme?.wallpaper_id?.asset ? assetGradient(theme.wallpaper_id.asset) : undefined;
  const themeBubble = theme?.bubble_id?.asset;

  // Resolve bubble cosmetics referenced by messages (server snapshots the
  // sender's active BUBBLE slot into message.cosmetic_id). Cached per id.
  const assetCache = useRef(new Map<string, CosmeticAsset>());
  const [, setAssetVer] = useState(0);
  useEffect(() => {
    if (!msgs) return;
    const ids = [...new Set(msgs.map((m) => m.cosmetic_id).filter((x): x is string => !!x))];
    const missing = ids.filter((id) => !assetCache.current.has(id)).slice(0, 12);
    if (!missing.length) return;
    let cancelled = false;
    (async () => {
      for (const id of missing) {
        try {
          const c = await api.get<Cosmetic>(`/catalog/${encodeURIComponent(id)}`);
          assetCache.current.set(id, c.asset ?? {});
        } catch {
          assetCache.current.set(id, {});
        }
      }
      if (!cancelled) setAssetVer((v) => v + 1);
    })();
    return () => { cancelled = true; };
  }, [msgs]);

  const bubbleStyleFor = (m: Message): CSSProperties | undefined => {
    const a = (m.cosmetic_id && assetCache.current.get(m.cosmetic_id)) || themeBubble;
    if (a && (a.gradient?.length ?? 0) >= 2) return { background: assetGradient(a) };
    return undefined;
  };

  if (err && !conv) return (
    <div>
      <div className="thread-head"><button className="icon-btn" onClick={onBack} aria-label="Back">←</button></div>
      <ErrorState message={err} onRetry={() => { loadConv(); loadMsgs(); }} />
    </div>
  );
  if (!conv || msgs === null) return (
    <div>
      <div className="thread-head"><button className="icon-btn" onClick={onBack} aria-label="Back">←</button></div>
      <Loading label="Opening chat…" />
    </div>
  );

  let lastDay = '';
  return (
    <div className="thread-wrap">
      <div className="thread-head">
        <button className="icon-btn" onClick={onBack} aria-label="Back">←</button>
        <Avatar profile={other} size={38} />
        <div className="who">
          <div className="nm">{conv.is_group ? (conv.title ?? 'Group') : (other?.display_name ?? '?')}</div>
          <div className="muted small">
            {streak !== null && streak > 0 ? <span className="streak-pill">🔥 {streak}</span> : '@' + (other?.username ?? '')}
          </div>
        </div>
        <button className="icon-btn" onClick={() => setShowPins((v) => !v)} aria-label="Pinned messages" title="Pinned">📌</button>
        <button className="icon-btn" onClick={() => { setSearchRes(searchRes ? null : []); }} aria-label="Search in chat" title="Search">🔍</button>
        <button className="icon-btn" onClick={() => setThemeOpen(true)} aria-label="Chat personality" title="Chat personality">🎨</button>
      </div>

      {showPins && (
        <div className="pin-bar">
          {pins.length === 0 ? <span className="muted">No pinned messages.</span> :
            pins.map((p) => <span key={p.id}>📌 {p.body?.slice(0, 40) ?? `[${p.kind}]`}</span>)}
        </div>
      )}

      {searchRes !== null && (
        <div className="card" style={{ margin: 12 }}>
          <div className="row">
            <input className="input" placeholder="Search messages…" value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') doSearch(); }} aria-label="Search messages" />
            <button className="btn small" onClick={doSearch} disabled={searching}>Go</button>
            <button className="icon-btn" onClick={() => { setSearchRes(null); setSearchQ(''); }} aria-label="Close search">✕</button>
          </div>
          <div style={{ marginTop: 8 }}>
            {searching ? <Loading label="Searching…" /> :
              searchRes.length === 0 ? <p className="muted small">No matches.</p> :
              searchRes.map((m) => (
                <div key={m.id} className="list-row">
                  <div className="grow"><strong>{m.sender_username}:</strong> {m.body?.slice(0, 80)}</div>
                  <span className="muted small">{timeAgo(m.created_at)}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      <div className="messages" style={wallpaper ? { backgroundImage: wallpaper } : undefined}>
        {msgs.length === 0 && (
          <Empty icon="✨" title="Start the conversation" hint="Messages you send carry your equipped bubble style." />
        )}
        {msgs.map((m) => {
          const mine = m.sender_id === me?.id;
          const dk = dayKey(m.created_at);
          const showDay = dk !== lastDay;
          lastDay = dk;
          return (
            <div key={m.id}>
              {showDay && <div className="date-divider"><span>{dayLabel(m.created_at)}</span></div>}
              <div className={`msg ${mine ? 'me' : 'them'}`}>
                <ErrorBoundary fallback={<div className="bubble">{m.deleted ? <em className="deleted-body">Deleted</em> : m.body}</div>}>
                  <MessageBubble msg={m} mine={mine} style={bubbleStyleFor(m)} onCosmeticInfo={setSheetCosmeticId} />
                </ErrorBoundary>
                {m.reactions.length > 0 && (
                  <div className="reactions">
                    {m.reactions.map((r) => (
                      <button key={r.emoji} className={'reaction-chip' + (r.users.includes(me?.id ?? -1) ? ' mine' : '')}
                        onClick={() => doReact(m, r.emoji)} title={r.count + ' reactions'}>
                        {r.emoji} {r.count}
                      </button>
                    ))}
                  </div>
                )}
                <div className="msg-actions">
                  <button onClick={() => setReactFor(m)} aria-label="React">😊</button>
                  {m.kind === 'text' && <button onClick={() => setReplyTo(m)}>Reply</button>}
                  {mine && !m.deleted && m.kind === 'text' && (
                    <>
                      <button onClick={() => { setEditing(m); setEditText(m.body ?? ''); }}>Edit</button>
                      <button onClick={() => doDelete(m)}>Delete</button>
                    </>
                  )}
                  <button onClick={() => doPin(m)}>Pin</button>
                  <button onClick={() => doForward(m)}>Forward</button>
                </div>
                <div className="msg-meta">
                  <span>{timeAgo(m.created_at)}</span>
                  {m.edited_at && <span>edited</span>}
                  {m.forwarded && <span>forwarded</span>}
                  {mine && <Receipt delivery={m.delivery} members={conv.members} meId={me?.id ?? 0} />}
                </div>
              </div>
            </div>
          );
        })}
        {typingUsers.size > 0 && (
          <div className="msg them"><div className="typing-ind" aria-label="Typing"><span /><span /><span /></div></div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="composer">
        {replyTo && (
          <div className="reply-bar">
            <span className="grow">↩ Replying to {replyTo.sender_username}: {(replyTo.body ?? '').slice(0, 60)}</span>
            <button className="icon-btn" onClick={() => setReplyTo(null)} aria-label="Cancel reply">✕</button>
          </div>
        )}
        <div className="composer-row">
          <button className="icon-btn" onClick={() => fileRef.current?.click()} disabled={uploading} aria-label="Attach file" title="Attach (10MB max)">
            {uploading ? '…' : '📎'}
          </button>
          <input ref={fileRef} type="file" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ''; }} />
          <textarea
            className="textarea" rows={1} value={draft} onChange={(e) => onInput(e.target.value)}
            placeholder="Message…" aria-label="Message"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
          />
          <button className="btn send-btn" onClick={send} disabled={!draft.trim()} aria-label="Send">➤</button>
        </div>
      </div>

      {editing && (
        <Modal title="Edit message" onClose={() => setEditing(null)}>
          <textarea className="textarea" value={editText} onChange={(e) => setEditText(e.target.value)} rows={3} />
          <div className="row" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
            <button className="btn secondary" onClick={() => setEditing(null)}>Cancel</button>
            <button className="btn" onClick={doEdit} disabled={!editText.trim()}>Save</button>
          </div>
        </Modal>
      )}

      {reactFor && (
        <Modal title="React" onClose={() => setReactFor(null)}>
          <div className="row wrap" style={{ gap: 10, justifyContent: 'center' }}>
            {EMOJIS.map((e) => (
              <button key={e} className="icon-btn" style={{ width: 48, height: 48, fontSize: 24 }}
                onClick={() => doReact(reactFor, e)} aria-label={`React ${e}`}>{e}</button>
            ))}
          </div>
        </Modal>
      )}

      {themeOpen && (
        <ChatThemePanel convId={convId} onClose={() => setThemeOpen(false)} onChanged={loadTheme} />
      )}
      {sheetCosmeticId && (
        <CosmeticSheet cosmeticId={sheetCosmeticId} onClose={() => setSheetCosmeticId(null)} />
      )}
    </div>
  );
}

function Receipt({ delivery, members, meId }: { delivery: Record<string, string>; members: Profile[]; meId: number }) {
  const others = members.filter((m) => m.id !== meId);
  if (!others.length) return null;
  const states = others.map((o) => delivery[String(o.id)] ?? delivery[o.id]);
  if (states.every((s) => s === 'read')) return <span title="Read">✓✓</span>;
  if (states.some((s) => s === 'delivered' || s === 'read')) return <span title="Delivered">✓✓</span>;
  return <span title="Sent">✓</span>;
}

function MessageBubble({ msg, mine, style, onCosmeticInfo }: {
  msg: Message; mine: boolean; style?: CSSProperties; onCosmeticInfo: (id: string) => void;
}) {
  if (msg.deleted) return <div className="bubble"><em className="deleted-body">Message deleted</em></div>;
  return (
    <div className="bubble" style={style}>
      {msg.reply_to && (
        <div className="reply-quote">↩ {msg.reply_to.sender_username}: {msg.reply_to.body ?? `[${msg.reply_to.kind}]`}</div>
      )}
      {msg.kind === 'image' && msg.media_url && (
        <img className="attached" src={msg.media_url.startsWith('http') ? msg.media_url : msg.media_url} alt="attachment" loading="lazy" />
      )}
      {msg.kind === 'video' && msg.media_url && (
        <video className="attached" src={msg.media_url} controls style={{ maxWidth: '100%', borderRadius: 12 }} />
      )}
      {msg.kind === 'file' && (
        <a href={msg.media_url ?? '#'} target="_blank" rel="noreferrer" style={{ color: mine ? '#fff' : undefined }}>
          📄 {msg.body ?? 'file'}
        </a>
      )}
      {(msg.kind === 'text' || (msg.body && msg.kind !== 'file')) && <span>{msg.body}</span>}
      {msg.kind === 'text' && msg.body && <LinkPreviewCard text={msg.body} />}
      {msg.cosmetic_id && (
        <button className="bubble-info" aria-label="About this bubble style" title="What bubble is this?"
          onClick={(e) => { e.stopPropagation(); onCosmeticInfo(msg.cosmetic_id!); }}>✨</button>
      )}
    </div>
  );
}
