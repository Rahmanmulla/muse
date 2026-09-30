import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { useApp } from '../store';
import type { LinkPreview } from '../types';

const URL_RE = /https?:\/\/[^\s<>"')]+/gi;

// Link preview card. The URL is NEVER fetched client-side — only the
// SSRF-guarded backend endpoint (GET /preview?url=) is called. Respects the
// user's link_previews setting; failures render nothing (never break chat).
export function LinkPreviewCard({ text }: { text: string }) {
  const { settings } = useApp();
  const [preview, setPreview] = useState<LinkPreview | null>(null);
  const cache = useRef(new Map<string, LinkPreview | null>());

  const urls = text.match(URL_RE);
  const url = urls?.[0];

  useEffect(() => {
    if (!url || settings['link_previews'] === false) return;
    if (cache.current.has(url)) {
      setPreview(cache.current.get(url) ?? null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const p = await api.get<LinkPreview>(`/preview?url=${encodeURIComponent(url)}`);
        cache.current.set(url, p);
        if (!cancelled) setPreview(p);
      } catch {
        cache.current.set(url, null);
        if (!cancelled) setPreview(null);
      }
    })();
    return () => { cancelled = true; };
  }, [url, settings]);

  if (!url || settings['link_previews'] === false || !preview?.title) return null;

  const host = (() => { try { return new URL(preview.url || url).hostname; } catch { return ''; } })();

  return (
    <a className="link-preview" href={url} target="_blank" rel="noreferrer noopener"
      onClick={(e) => e.stopPropagation()}>
      {preview.image && (
        <img src={preview.image} alt="" loading="lazy" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
      )}
      <div className="lp-body">
        <div className="lp-site">{preview.site_name || host}</div>
        <div className="lp-title">{preview.title}</div>
        {preview.description && <div className="lp-desc">{preview.description.slice(0, 140)}</div>}
      </div>
    </a>
  );
}
