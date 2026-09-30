import { useCallback, useEffect, useRef, useState } from 'react';
import { getToken } from './api';
import { AppProvider, useApp } from './store';
import { ErrorBoundary } from './components/ui';
import { Auth, AuthLoading } from './screens/Auth';
import { Onboarding } from './screens/Onboarding';
import { Requests } from './screens/Requests';
import { Chats } from './screens/Chats';
import { ChatView } from './screens/ChatView';
import { Collection } from './screens/Collection';
import { Shop, DailyModal } from './screens/Shop';
import { Streaks } from './screens/Streaks';
import { Progress } from './screens/Progress';
import { SafeProfile } from './screens/Profile';
import { Settings } from './screens/Settings';

type Route =
  | { name: 'login' } | { name: 'signup' } | { name: 'onboarding' }
  | { name: 'chats' } | { name: 'requests' } | { name: 'collection' } | { name: 'shop' }
  | { name: 'streaks' } | { name: 'progress' } | { name: 'profile' } | { name: 'settings' }
  | { name: 'chat'; id: number }
  | { name: 'user'; username: string };

function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, '');
  const parts = h.split('/');
  switch (parts[0]) {
    case 'login': return { name: 'login' };
    case 'signup': return { name: 'signup' };
    case 'onboarding': return { name: 'onboarding' };
    case 'requests': return { name: 'requests' };
    case 'collection': return { name: 'collection' };
    case 'shop': return { name: 'shop' };
    case 'streaks': return { name: 'streaks' };
    case 'progress': return { name: 'progress' };
    case 'profile': return { name: 'profile' };
    case 'settings': return { name: 'settings' };
    case 'user': return parts[1] ? { name: 'user', username: decodeURIComponent(parts[1]) } : { name: 'chats' };
    case 'chat': {
      const id = parseInt(parts[1], 10);
      return Number.isFinite(id) ? { name: 'chat', id } : { name: 'chats' };
    }
    default: return { name: 'chats' };
  }
}

const TABS = [
  { name: 'chats', icon: '💬', label: 'Chats', hash: '#/chats' },
  { name: 'collection', icon: '🎒', label: 'Styles', hash: '#/collection' },
  { name: 'shop', icon: '🛍️', label: 'Shop', hash: '#/shop' },
  { name: 'streaks', icon: '🔥', label: 'Streaks', hash: '#/streaks' },
  { name: 'profile', icon: '🙂', label: 'You', hash: '#/profile' },
] as const;

function Shell() {
  const { me, refreshMe, refreshWallet, refreshSettings, refreshRequests, toast, ws, requestsCount } = useApp();
  const [route, setRoute] = useState<Route>(parseHash);
  const [booted, setBooted] = useState(false);
  const [chatRefresh, setChatRefresh] = useState(0);
  const [dailyOpen, setDailyOpen] = useState(false);
  const meRef = useRef(me);
  meRef.current = me;

  const boot = useCallback(async () => {
    if (!getToken()) {
      setBooted(true);
      const r = parseHash();
      if (r.name !== 'login' && r.name !== 'signup' && r.name !== 'onboarding') window.location.hash = '#/login';
      return;
    }
    try {
      await Promise.all([refreshMe(), refreshWallet(), refreshSettings(), refreshRequests()]);
    } catch {
      // api client already redirects to login on 401
    } finally {
      setBooted(true);
    }
  }, [refreshMe, refreshWallet, refreshSettings, refreshRequests]);

  useEffect(() => {
    const onHash = () => {
      setRoute(parseHash());
      // A fresh login/signup lands here with a token but no loaded profile
      // (boot only runs on mount) — boot now instead of hanging on splash.
      if (getToken() && !meRef.current) boot();
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [boot]);

  useEffect(() => { boot(); }, [boot]);

  useEffect(() => {
    const onUnauth = () => { setBooted(true); setRoute({ name: 'login' }); };
    window.addEventListener('stip:unauthorized', onUnauth);
    return () => window.removeEventListener('stip:unauthorized', onUnauth);
  }, []);

  // reward/streak toasts from anywhere
  useEffect(() => {
    return ws.on((f) => {
      if (f.type === 'streak.updated') {
        const d = f.data as { count?: number } | undefined;
        if (d?.count) toast(`🔥 Streak: ${d.count} days!`);
      }
    });
  }, [ws, toast]);

  // daily reward nudge once per session
  useEffect(() => {
    if (me && !sessionStorage.getItem('stip_daily_nudge')) {
      sessionStorage.setItem('stip_daily_nudge', '1');
      setDailyOpen(true);
    }
  }, [me]);

  if (!booted || (getToken() && !me)) {
    return <div className="app-shell"><AuthLoading /></div>;
  }

  if (!getToken() || route.name === 'login' || route.name === 'signup' || route.name === 'onboarding') {
    return (
      <div className="app-shell">
        {route.name === 'login'
          ? <Auth mode="login" onDone={() => { window.location.hash = '#/chats'; }} />
          : <Onboarding onDone={() => { window.location.hash = '#/chats'; }} />}
      </div>
    );
  }

  const go = (hash: string) => { window.location.hash = hash; };

  const activeTab =
    route.name === 'chat' || route.name === 'requests' ? 'chats'
    : route.name === 'settings' || route.name === 'user' || route.name === 'progress' ? 'profile'
    : (['chats', 'collection', 'shop', 'streaks', 'profile'] as string[]).includes(route.name) ? route.name
    : null;

  const hideTabs = route.name === 'chat' || route.name === 'settings' || route.name === 'requests';

  return (
    <div className="app-shell">
      {route.name === 'chats' && <Chats refreshKey={chatRefresh} onOpen={(id) => go(`#/chat/${id}`)} />}
      {route.name === 'requests' && <Requests onOpenChat={(id) => go(`#/chat/${id}`)} onBack={() => go('#/chats')} />}
      {route.name === 'chat' && (
        <ErrorBoundary fallback={<div className="screen"><p>Chat failed to load.</p><button className="btn" onClick={onBackFallback}>Back</button></div>}>
          <ChatView convId={route.id} onBack={() => { setChatRefresh((k) => k + 1); go('#/chats'); }} />
        </ErrorBoundary>
      )}
      {route.name === 'collection' && <Collection />}
      {route.name === 'shop' && <Shop />}
      {route.name === 'streaks' && <Streaks />}
      {route.name === 'progress' && <Progress />}
      {route.name === 'profile' && (
        <SafeProfile onSettings={() => go('#/settings')} onCollection={() => go('#/collection')} />
      )}
      {route.name === 'user' && (
        <SafeProfile username={route.username} onSettings={() => go('#/settings')} onCollection={() => go('#/collection')} />
      )}
      {route.name === 'settings' && <Settings onBack={() => go('#/profile')} />}

      {dailyOpen && <DailyModal onClose={() => setDailyOpen(false)} />}

      {!hideTabs && (
        <nav className="tabbar" aria-label="Main tabs">
          {TABS.map((t) => (
            <button key={t.name} className={activeTab === t.name ? 'active' : ''} onClick={() => go(t.hash)}
              aria-current={activeTab === t.name ? 'page' : undefined}>
              <span className="tico" aria-hidden="true" style={{ position: 'relative' }}>
                {t.icon}
                {t.name === 'chats' && requestsCount > 0 && (
                  <span className="nav-badge" aria-label={`${requestsCount} pending message requests`}>{requestsCount}</span>
                )}
              </span>
              {t.label}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}

function onBackFallback() {
  window.location.hash = '#/chats';
}

export default function App() {
  return (
    <ErrorBoundary
      fallback={
        <div className="app-shell">
          <div className="screen" style={{ textAlign: 'center', paddingTop: 80 }}>
            <div style={{ fontSize: 48 }}>🛰️</div>
            <h2>Something went wrong</h2>
            <p className="muted">STIP hit an unexpected error. Your chats are safe on the server.</p>
            <button className="btn" onClick={() => window.location.reload()}>Reload</button>
          </div>
        </div>
      }
    >
      <AppProvider>
        <Shell />
        <Toasts />
      </AppProvider>
    </ErrorBoundary>
  );
}

function Toasts() {
  const { toasts } = useApp();
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toast">{t.text}</div>
      ))}
    </div>
  );
}
