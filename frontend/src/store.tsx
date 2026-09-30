import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api, getToken, setAuth } from './api';
import { useWebSocket, type WSApi } from './hooks/useWebSocket';
import type { Profile } from './types';

export interface Toast {
  id: number;
  text: string;
}

interface AppState {
  me: Profile | null;
  balances: Record<string, number>;
  settings: Record<string, unknown>;
  lowEffects: boolean;
  reduceMotion: boolean;
  theme: string;
  resolvedTheme: 'light' | 'dark';
  requestsCount: number;
  toasts: Toast[];
  ws: WSApi;
  toast: (text: string) => void;
  refreshMe: () => Promise<void>;
  refreshWallet: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  refreshRequests: () => Promise<void>;
  setLowEffects: (v: boolean) => void;
  logout: () => Promise<void>;
}

const Ctx = createContext<AppState | null>(null);

let toastId = 1;

export function AppProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Profile | null>(null);
  const [balances, setBalances] = useState<Record<string, number>>({});
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [lowEffects, setLowEffectsState] = useState(
    () => localStorage.getItem('stip_low_effects') === '1'
  );
  const [requestsCount, setRequestsCount] = useState(0);
  const [systemDark, setSystemDark] = useState(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-color-scheme: dark)').matches
  );
  const authed = !!getToken();
  const ws = useWebSocket(authed);

  const toast = useCallback((text: string) => {
    const id = toastId++;
    setToasts((t) => [...t.slice(-3), { id, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);

  const refreshMe = useCallback(async () => {
    const p = await api.get<Profile>('/users/me');
    setMe(p);
  }, []);

  const refreshWallet = useCallback(async () => {
    try {
      const w = await api.get<{ balances: Record<string, number> }>('/wallet');
      setBalances(w.balances ?? {});
    } catch {
      /* wallet is auxiliary — never break the app */
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    try {
      const s = await api.get<Record<string, unknown>>('/users/me/settings');
      setSettings(s ?? {});
    } catch {
      /* ignore */
    }
  }, []);

  const refreshRequests = useCallback(async () => {
    try {
      const r = await api.get<{ id: number }[]>('/requests/inbox');
      setRequestsCount(r.length);
    } catch {
      /* inbox is auxiliary — never break the app */
    }
  }, []);

  const setLowEffects = useCallback((v: boolean) => {
    setLowEffectsState(v);
    localStorage.setItem('stip_low_effects', v ? '1' : '0');
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      /* ignore */
    }
    setAuth(null);
    setMe(null);
    window.location.hash = '#/login';
  }, []);

  // OS-level reduced motion + server setting
  const reduceMotion = useMemo(() => {
    if (settings['reduced_motion'] === true) return true;
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }
    return false;
  }, [settings]);

  // Theme: server setting (system|dark|light) → resolved light/dark.
  const theme = (settings['theme'] as string) || 'system';
  const resolvedTheme: 'light' | 'dark' = theme === 'light' ? 'light' : theme === 'dark' ? 'dark' : systemDark ? 'dark' : 'light';

  // Follow OS color-scheme changes when theme=system
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  // Apply motion class + theme attribute to document
  useEffect(() => {
    document.documentElement.classList.toggle('reduce-motion', reduceMotion);
    document.documentElement.classList.toggle('low-effects', lowEffects);
    document.documentElement.dataset.theme = resolvedTheme;
  }, [reduceMotion, lowEffects, resolvedTheme]);

  // Global WS → toast + wallet refresh triggers
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const refreshRequestsRef = useRef(refreshRequests);
  refreshRequestsRef.current = refreshRequests;
  useEffect(() => {
    return ws.on((f) => {
      try {
        if (f.type === 'notification.new') {
          const n = f.notification as { title?: string } | undefined;
          if (n?.title) toastRef.current(`🔔 ${n.title}`);
        } else if (f.type === 'reward.granted') {
          const d = f.data as { title?: string } | undefined;
          toastRef.current(`🎁 ${typeof d?.title === 'string' ? d.title : 'Reward received'}`);
          refreshWallet();
        } else if (f.type === 'inventory.updated') {
          refreshWallet();
        } else if (f.type === 'request.new') {
          refreshRequestsRef.current();
          const from = (f.from_user as { username?: string } | undefined)?.username;
          toastRef.current(`📥 Message request${from ? ` from @${from}` : ''}`);
        } else if (f.type === 'request.accepted' || f.type === 'request.rejected') {
          refreshRequestsRef.current();
        }
      } catch {
        /* never break the socket */
      }
    });
  }, [ws, refreshWallet]);

  const value: AppState = {
    me, balances, settings, lowEffects, reduceMotion, theme, resolvedTheme,
    requestsCount, toasts, ws,
    toast, refreshMe, refreshWallet, refreshSettings, refreshRequests, setLowEffects, logout,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp outside provider');
  return v;
}
