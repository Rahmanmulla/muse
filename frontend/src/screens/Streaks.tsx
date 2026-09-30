import { useCallback, useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { Avatar, Empty, ErrorState, Loading, Modal } from '../components/ui';
import type { Streak, StreakDetail } from '../types';

export function Streaks() {
  const [streaks, setStreaks] = useState<Streak[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [detailFor, setDetailFor] = useState<Streak | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      setStreaks(await api.get<Streak[]>('/streaks'));
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="topbar"><h1>🔥 Streaks</h1></div>
      <div className="screen">
        {err ? <ErrorState message={err} onRetry={load} /> :
          streaks === null ? <Loading label="Loading streaks…" /> :
          streaks.length === 0 ? (
            <Empty icon="🔥" title="No streaks yet"
              hint="Message a friend back and forth — a day counts once you've both sent at least one message." />
          ) : (
            streaks.map((s) => (
              <div key={s.with_user?.id ?? 'x'} className="card clickable" onClick={() => setDetailFor(s)} role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') setDetailFor(s); }}>
                <div className="row">
                  <span className="streak-fire" aria-hidden="true">🔥</span>
                  <Avatar profile={s.with_user ? { display_name: s.with_user.display_name } : null} size={44} />
                  <div className="grow">
                    <strong>{s.with_user?.display_name ?? 'Unknown'}</strong>
                    <div className="muted small">Longest: {s.longest} days · {s.message_count} messages</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 22, fontWeight: 800 }}>{s.count}</div>
                    <div className="muted small">days</div>
                  </div>
                </div>
              </div>
            ))
          )}
      </div>
      {detailFor?.with_user && <StreakDetailModal userId={detailFor.with_user.id} name={detailFor.with_user.display_name} onClose={() => setDetailFor(null)} />}
    </div>
  );
}

function StreakDetailModal({ userId, name, onClose }: { userId: number; name: string; onClose: () => void }) {
  const [d, setD] = useState<StreakDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<StreakDetail>(`/streaks/${userId}`).then(setD).catch((e) => setErr(apiErrorMessage(e)));
  }, [userId]);

  return (
    <Modal title={`🔥 ${name}`} onClose={onClose}>
      {err ? <ErrorState message={err} /> :
        d === null ? <Loading label="Loading streak…" /> : (
          <>
            <div className="row" style={{ justifyContent: 'space-around', textAlign: 'center', marginBottom: 12 }}>
              <div><div style={{ fontSize: 28, fontWeight: 800 }}>{d.count}</div><div className="muted small">current</div></div>
              <div><div style={{ fontSize: 28, fontWeight: 800 }}>{d.longest}</div><div className="muted small">longest</div></div>
              <div><div style={{ fontSize: 28, fontWeight: 800 }}>{d.message_count}</div><div className="muted small">messages</div></div>
            </div>
            {d.last_active_day && <p className="muted small">Last active day: {new Date(d.last_active_day).toLocaleDateString()}</p>}
            {d.milestones.length > 0 && (
              <>
                <h4>Milestones</h4>
                {d.milestones.map((m) => (
                  <div key={m} className="list-row"><span>🏅</span><span className="grow">{m}</span></div>
                ))}
              </>
            )}
          </>
        )}
    </Modal>
  );
}
