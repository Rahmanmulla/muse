import { useCallback, useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { Empty, ErrorState, Loading, timeAgo } from '../components/ui';
import type { MsgRequest, WSFrame } from '../types';

// v3 message requests: strangers land here instead of the chat list.
// Accept reveals the shadow conversation; reject deletes it (optionally with a report).
export function Requests({ onOpenChat, onBack }: { onOpenChat: (id: number) => void; onBack: () => void }) {
  const { ws, toast, refreshRequests } = useApp();
  const [rows, setRows] = useState<MsgRequest[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const r = await api.get<MsgRequest[]>('/requests/inbox');
      setRows(r);
      refreshRequests();
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, [refreshRequests]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    return ws.on((f: WSFrame) => {
      if (f.type === 'request.new' || f.type === 'request.accepted' || f.type === 'request.rejected') {
        load();
      }
    });
  }, [ws, load]);

  const accept = async (r: MsgRequest) => {
    setBusyId(r.id);
    try {
      const res = await api.post<{ ok: boolean; conversation_id: number }>(`/requests/${r.id}/accept`, {});
      toast('✅ Request accepted');
      onOpenChat(res.conversation_id);
    } catch (e) {
      toast(apiErrorMessage(e));
      setBusyId(null);
    }
  };

  const reject = async (r: MsgRequest, report: boolean) => {
    let reason: string | undefined;
    if (report) {
      reason = window.prompt('Report reason (optional):') ?? undefined;
      if (reason === null) return;
    } else if (!window.confirm(`Reject the request from @${r.from_user?.username ?? '?'}?`)) {
      return;
    }
    setBusyId(r.id);
    try {
      await api.post(`/requests/${r.id}/reject`, report ? { report: true, reason } : {});
      toast(report ? '🛡️ Rejected and reported' : 'Request rejected');
      load();
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <div className="topbar">
        <button className="icon-btn" onClick={onBack} aria-label="Back">←</button>
        <h1>📥 Message requests</h1>
      </div>
      <div className="screen">
        <p className="muted small" style={{ marginTop: 0 }}>
          People who aren't your contacts yet appear here first. Nothing lands in your chats until you accept.
        </p>
        {err ? <ErrorState message={err} onRetry={load} /> :
          rows === null ? <Loading label="Loading requests…" /> :
          rows.length === 0 ? (
            <Empty icon="📥" title="No requests" hint="When someone new messages you, it'll show up here." />
          ) : (
            rows.map((r) => (
              <div key={r.id} className="card">
                <div className="list-row" style={{ borderBottom: 'none', paddingBottom: 4 }}>
                  <div className="grow">
                    <strong>{r.from_user?.display_name ?? '?'}</strong>{' '}
                    <span className="muted small">@{r.from_user?.username ?? '?'}</span>
                    <div className="muted small">{timeAgo(r.created_at)}</div>
                  </div>
                </div>
                {r.message_preview && (
                  <p style={{ margin: '4px 0 10px', fontSize: 14 }}>"{r.message_preview}"</p>
                )}
                <div className="row wrap" style={{ gap: 8 }}>
                  <button className="btn small" disabled={busyId === r.id} onClick={() => accept(r)}>
                    {busyId === r.id ? '…' : 'Accept'}
                  </button>
                  <button className="btn small secondary" disabled={busyId === r.id} onClick={() => reject(r, false)}>
                    Reject
                  </button>
                  <button className="btn small danger" disabled={busyId === r.id} onClick={() => reject(r, true)}>
                    Reject + report
                  </button>
                </div>
              </div>
            ))
          )}
      </div>
    </div>
  );
}
