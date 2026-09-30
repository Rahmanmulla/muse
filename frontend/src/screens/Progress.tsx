import { useCallback, useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { CosmeticThumb, Currency, Empty, ErrorState, Loading, ProgressBar, SectionTitle, assetGradient, fmtDate } from '../components/ui';
import type { Achievement, GameEvent, Notification, WalletTx } from '../types';

type Tab = 'achievements' | 'events' | 'notifications' | 'wallet';

export function Progress({ initialTab = 'achievements' }: { initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  return (
    <div>
      <div className="topbar"><h1>🏆 Progress</h1></div>
      <div className="filter-row" style={{ padding: '4px 16px 10px' }}>
        {(['achievements', 'events', 'notifications', 'wallet'] as Tab[]).map((t) => (
          <button key={t} className={'chip' + (tab === t ? ' active' : '')} onClick={() => setTab(t)}>
            {t === 'achievements' ? '🏆 Achievements' : t === 'events' ? '🎪 Events' : t === 'notifications' ? '🔔 Notifications' : '💰 Wallet'}
          </button>
        ))}
      </div>
      <div className="screen" style={{ paddingTop: 0 }}>
        {tab === 'achievements' && <AchievementsTab />}
        {tab === 'events' && <EventsTab />}
        {tab === 'notifications' && <NotificationsTab />}
        {tab === 'wallet' && <WalletTab />}
      </div>
    </div>
  );
}

function AchievementsTab() {
  const [list, setList] = useState<Achievement[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    setErr(null);
    try { setList(await api.get<Achievement[]>('/achievements')); }
    catch (e) { setErr(apiErrorMessage(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);
  if (err) return <ErrorState message={err} onRetry={load} />;
  if (list === null) return <Loading label="Loading achievements…" />;
  const unlocked = list.filter((a) => a.unlocked).length;
  return (
    <>
      <p className="muted">{unlocked}/{list.length} unlocked</p>
      {list.map((a) => (
        <div key={a.id} className="card" style={{ opacity: a.unlocked ? 1 : 0.85 }}>
          <div className="row">
            <span style={{ fontSize: 30 }} aria-hidden="true">{a.unlocked ? '🏆' : '🔒'}</span>
            <div className="grow">
              <strong>{a.name}</strong>
              <div className="muted small">{a.description}</div>
              {!a.unlocked && a.target > 1 && (
                <><ProgressBar value={a.progress} max={a.target} label={a.name} />
                <div className="muted small">{a.progress}/{a.target}</div></>
              )}
              {a.unlocked && a.unlocked_at && <div className="muted small">Unlocked {fmtDate(a.unlocked_at)}</div>}
            </div>
          </div>
          <div className="muted small" style={{ marginTop: 6 }}>
            Reward: {a.reward.shards > 0 && `${a.reward.shards} 🔷 `}{a.reward.gems > 0 && `${a.reward.gems} 💎 `}
            {a.reward.cosmetic_id && '🎨 cosmetic'}
          </div>
        </div>
      ))}
    </>
  );
}

function EventsTab() {
  const [events, setEvents] = useState<GameEvent[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<GameEvent | null>(null);
  const load = useCallback(async () => {
    setErr(null);
    try { setEvents(await api.get<GameEvent[]>('/events')); }
    catch (e) { setErr(apiErrorMessage(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const open = async (id: string) => {
    setOpenId(id);
    try { setDetail(await api.get<GameEvent>(`/events/${id}`)); }
    catch { /* ignore */ }
  };

  if (err) return <ErrorState message={err} onRetry={load} />;
  if (events === null) return <Loading label="Loading events…" />;
  if (events.length === 0) return <Empty icon="🎪" title="No events" hint="Check back soon for seasonal events." />;

  const ev = detail ?? events.find((e) => e.id === openId) ?? null;
  return (
    <>
      {events.map((e) => (
        <div key={e.id} className="card clickable" onClick={() => open(e.id)} role="button" tabIndex={0}
          onKeyDown={(ev2) => { if (ev2.key === 'Enter') open(e.id); }}>
          <div className="row">
            <div className="cos-thumb" style={{ width: 52, height: 52, background: assetGradient(e.banner_asset) }}>
              <span aria-hidden="true">{e.banner_asset?.emoji ?? '🎪'}</span>
            </div>
            <div className="grow">
              <strong>{e.name}</strong>
              <div className="muted small">{e.description}</div>
              <div className="muted small">{e.is_live ? '🟢 Live now' : `Status: ${e.status}`}</div>
            </div>
          </div>
        </div>
      ))}
      {ev && (
        <div className="card" style={{ marginTop: 12 }}>
          <SectionTitle>{ev.name} — challenges</SectionTitle>
          {(ev.challenges ?? []).map((c) => (
            <div key={c.id} style={{ marginBottom: 10 }}>
              <div className="row">
                <span className="grow"><strong>{c.name}</strong> {c.completed && '✅'}</span>
                <span className="muted small">{c.progress}/{c.target}</span>
              </div>
              <ProgressBar value={c.progress} max={c.target} label={c.name} />
            </div>
          ))}
          {(ev.shop_items ?? []).length > 0 && (
            <>
              <SectionTitle>Event shop</SectionTitle>
              <div className="grid">
                {(ev.shop_items ?? []).map((i) => (
                  <div key={i.cosmetic_id} className="cos-card">
                    <CosmeticThumb cosmetic={{ asset: i.asset, name: i.name, rarity: i.rarity as 'common' }} size={48} />
                    <span className="nm">{i.name}</span>
                    <span className="muted small">{i.price_shards > 0 ? `${i.price_shards} 🔷` : `${i.price_gems} 💎`}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}

function NotificationsTab() {
  const { toast, ws } = useApp();
  const [list, setList] = useState<Notification[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    setErr(null);
    try { setList(await api.get<Notification[]>('/notifications?limit=50')); }
    catch (e) { setErr(apiErrorMessage(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    return ws.on((f) => {
      if (f.type === 'notification.new') load();
    });
  }, [ws, load]);

  const markAll = async () => {
    try {
      await api.post('/notifications/read', { ids: 'all' });
      setList((l) => (l ?? []).map((n) => ({ ...n, read: true })));
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  if (err) return <ErrorState message={err} onRetry={load} />;
  if (list === null) return <Loading label="Loading notifications…" />;
  return (
    <>
      {list.some((n) => !n.read) && (
        <button className="btn small secondary" onClick={markAll} style={{ marginBottom: 10 }}>Mark all read</button>
      )}
      {list.length === 0 ? <Empty icon="🔔" title="All caught up" hint="New rewards, streaks and mentions will show up here." /> :
        list.map((n) => (
          <div key={n.id} className="card" style={{ opacity: n.read ? 0.7 : 1 }}>
            <div className="row">
              <div className="grow">
                <strong>{!n.read && '● '}{n.title}</strong>
                <div className="muted small">{n.body}</div>
                <div className="muted small">{fmtDate(n.created_at)}</div>
              </div>
            </div>
          </div>
        ))}
    </>
  );
}

function WalletTab() {
  const { balances } = useApp();
  const [txs, setTxs] = useState<WalletTx[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    setErr(null);
    try { setTxs(await api.get<WalletTx[]>('/wallet/transactions?limit=50')); }
    catch (e) { setErr(apiErrorMessage(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <>
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-around' }}>
          <div style={{ textAlign: 'center' }}><Currency amount={balances.shards ?? 0} kind="shards" /><div className="muted small">Shards</div></div>
          <div style={{ textAlign: 'center' }}><Currency amount={balances.gems ?? 0} kind="gems" /><div className="muted small">Gems</div></div>
          <div style={{ textAlign: 'center' }}><Currency amount={balances.event_tokens ?? 0} kind="event_tokens" /><div className="muted small">Event tokens</div></div>
        </div>
      </div>
      <SectionTitle>History</SectionTitle>
      {err ? <ErrorState message={err} onRetry={load} /> :
        txs === null ? <Loading label="Loading transactions…" /> :
        txs.length === 0 ? <Empty icon="🧾" title="No transactions" hint="Earn shards from daily rewards and achievements." /> :
        txs.map((t) => (
          <div key={t.id} className="list-row">
            <span style={{ fontSize: 20 }} aria-hidden="true">{t.amount_delta >= 0 ? '➕' : '➖'}</span>
            <div className="grow">
              <div><strong style={{ color: t.amount_delta >= 0 ? 'var(--good)' : 'var(--bad)' }}>
                {t.amount_delta >= 0 ? '+' : ''}{t.amount_delta}
              </strong> <span className="muted small">{t.currency}</span></div>
              <div className="muted small">{t.reason} · {t.source}</div>
            </div>
            <span className="muted small">{fmtDate(t.created_at)}</span>
          </div>
        ))}
    </>
  );
}
