// External content is parsed into trusted URLs; provider HTML is never executed.
function externalHttpsUrl(value) {
  try {
    const url = new URL(String(value || '').trim());
    return url.protocol === 'https:' && !url.username && !url.password && !url.port ? url : null;
  } catch { return null; }
}

// ProtoPedia's renderer sends each anchor's textContent to /api/oembed.
// Explicit links survive HTML parsing and compact output; bare URL text may not.
function createPublishedEmbedLink(value) {
  const url = externalHttpsUrl(String(value || '').trim().replace(/^http:/i, 'https:'));
  if (!url) return null;
  const paragraph = document.createElement('p');
  paragraph.style.margin = '0';
  const link = document.createElement('a');
  link.href = url.href;
  link.textContent = url.href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  paragraph.append(link);
  return paragraph;
}

function externalDocumentInfo(value) {
  const url = externalHttpsUrl(value);
  if (!url) return null;
  const path = url.pathname;
  if (url.hostname === 'drive.google.com') {
    const id = path.match(/^\/file\/d\/([\w-]+)(?:\/(?:view|preview|edit))?\/?$/)?.[1]
      || (/^\/(?:open|uc)$/.test(path) ? url.searchParams.get('id') : '');
    if (!id || !/^[\w-]+$/.test(id)) return null;
    const resourceKey = url.searchParams.get('resourcekey');
    const suffix = resourceKey ? `?resourcekey=${encodeURIComponent(resourceKey)}` : '';
    return {provider:'drive', label:'Googleドライブ（PDF）', url:`https://drive.google.com/file/d/${id}/view${suffix}`,
      embedUrl:`https://drive.google.com/file/d/${id}/preview${suffix}`};
  }
  if (url.hostname === 'speakerdeck.com' && /^\/[^/]+\/[^/]+\/?$/.test(path) && !path.startsWith('/player/')) {
    url.search = ''; url.hash = '';
    return {provider:'speakerdeck', label:'Speaker Deck', url:url.href,
      oembed:`https://speakerdeck.com/oembed.json?url=${encodeURIComponent(url.href)}`};
  }
  if (['www.slideshare.net', 'slideshare.net'].includes(url.hostname)
    && /^\/(?:slideshow\/[^/]+\/\d+|[^/]+\/[^/]+)\/?$/.test(path)
    && !/^\/(?:slideshow\/embed_code|api|login|signup)(?:\/|$)/.test(path)) {
    url.search = ''; url.hash = '';
    return {provider:'slideshare', label:'SlideShare', url:url.href,
      oembed:`https://www.slideshare.net/api/oembed/2?url=${encodeURIComponent(url.href)}&format=json`};
  }
  return null;
}

function trustedDocumentEmbed(value, provider) {
  const url = externalHttpsUrl(String(value || '').startsWith('//') ? `https:${value}` : value);
  if (!url) return '';
  if (provider === 'speakerdeck' && url.hostname === 'speakerdeck.com' && /^\/player\/[a-f\d]{32}\/?$/i.test(url.pathname)) return url.href;
  if (provider === 'slideshare' && ['www.slideshare.net', 'slideshare.net'].includes(url.hostname)
    && /^\/slideshow\/embed_code\/(?:key\/[\w-]+|\d+)\/?$/.test(url.pathname)) return url.href;
  return '';
}

function documentEmbedFromCode(code, provider) {
  const parsed = new DOMParser().parseFromString(String(code || ''), 'text/html');
  const frame = parsed.querySelector('iframe[src]');
  const direct = trustedDocumentEmbed(frame?.getAttribute('src') || code, provider);
  if (direct) return direct;
  if (provider === 'speakerdeck') {
    const id = parsed.querySelector('script[data-id]')?.getAttribute('data-id');
    if (/^[a-f\d]{32}$/i.test(id || '')) return `https://speakerdeck.com/player/${id}`;
  }
  return '';
}

function renderExternalDocument(component) {
  if (component?.dataset.insertedComponent !== 'document') return;
  const info = externalDocumentInfo(component.dataset.documentUrl);
  const height = Math.max(180, Math.min(900, Number(component.dataset.documentHeight) || 420));
  const title = component.dataset.documentTitle || info?.label || 'スライド';
  const embed = info?.embedUrl || trustedDocumentEmbed(component.dataset.documentEmbedUrl, info?.provider);
  component.contentEditable = 'false';
  component.style.cssText = 'margin:14px 0;max-width:100%;';
  component.replaceChildren();
  if (embed && info) {
    const wrap = document.createElement('div');
    wrap.style.cssText = `position:relative;width:100%;height:${height}px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;overflow:hidden;box-sizing:border-box;`;
    const frame = document.createElement('iframe');
    if (articleExternalContentAllowed) frame.src = embed;
    else frame.dataset.securitySrc = embed;
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
    frame.setAttribute('referrerpolicy', 'no-referrer');
    frame.title = title;
    frame.loading = 'lazy';
    frame.setAttribute('allowfullscreen', '');
    frame.style.cssText = 'width:100%;height:100%;border:0;';
    const catcher = document.createElement('div');
    catcher.dataset.embedClickCatcher = 'true';
    catcher.style.cssText = 'position:absolute;inset:0;cursor:pointer;';
    wrap.append(frame, catcher);
    component.append(wrap);
  } else {
    const notice = document.createElement('div');
    notice.style.cssText = 'padding:28px 16px;border:1px dashed #94a3b8;border-radius:8px;text-align:center;background:#f8fafc;color:#475569;';
    notice.textContent = info ? `${title}：設定の「プレビュー取得」で表示します。取得できない場合も公開用URLは保持されます。`
      : '設定でSpeaker Deck・SlideShare、またはGoogleドライブ上のPDF共有URLを入力してください。';
    component.append(notice);
  }
  if (info) {
    const link = document.createElement('a');
    link.href = info.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    link.textContent = `${title}を開く ↗`;
    link.style.cssText = 'display:inline-block;margin-top:8px;font-size:13px;';
    component.append(link);
  }
  if (component.dataset.documentCaption) {
    const caption = document.createElement('p');
    caption.textContent = component.dataset.documentCaption;
    caption.style.cssText = 'margin:8px 0;color:#64748b;font-size:13px;';
    component.append(caption);
  }
}

const externalFetchVersions = new WeakMap();
async function resolveDocumentPreview(component) {
  if (!articleExternalContentAllowed) { setStatus('記事上部の「外部コンテンツを読み込む」を押してください'); return false; }
  const info = externalDocumentInfo(component?.dataset.documentUrl);
  if (!info || !component.isConnected) return false;
  if (info.embedUrl) { renderExternalDocument(component); return true; }
  const originalUrl = component.dataset.documentUrl;
  const version = (externalFetchVersions.get(component) || 0) + 1;
  externalFetchVersions.set(component, version);
  const current = () => component.isConnected && component.dataset.documentUrl === originalUrl && externalFetchVersions.get(component) === version;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  setStatus('スライドのプレビューを取得しています…');
  try {
    const response = await fetch(info.oembed, {signal:controller.signal, credentials:'omit'});
    if (!response.ok) throw new Error('取得できませんでした');
    const data = await response.json();
    const embed = documentEmbedFromCode(data.html, info.provider);
    if (!embed) throw new Error('対応するプレビューがありません');
    if (!current()) return false;
    component.dataset.documentEmbedUrl = embed;
    if (!component.dataset.documentTitle && typeof data.title === 'string') component.dataset.documentTitle = data.title;
    renderExternalDocument(component);
    capturePreviewEdits();
    if (activeInsertedComponent === component) document.querySelector('.inserted-component-properties')?._sync?.();
    setStatus('スライドのプレビューを取得しました');
    return true;
  } catch {
    if (current()) setStatus('プレビューを取得できませんでした。URLは保存済みです。必要なら「プレビュー補助」に公式の埋め込みコードを貼り付けてください。');
    return false;
  } finally { clearTimeout(timeout); }
}
