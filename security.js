// DOMPurify is vendored and pinned; never fetch the sanitizer at runtime.

const ARTICLE_MAX_BYTES = 5 * 1024 * 1024;
function checkArticleTextSize(value) {
  const text = String(value || '');
  if (text.length > ARTICLE_MAX_BYTES || new TextEncoder().encode(text).length > ARTICLE_MAX_BYTES) {
    throw new Error('読み込みデータは5MB以下にしてください');
  }
  return text;
}
function checkArticleStructure(value) {
  const stack = [[value, 0]];
  let count = 0, size = 0;
  while (stack.length) {
    const [item, depth] = stack.pop();
    if (++count > 20000 || depth > 64) throw new Error('読み込みデータの項目数・階層が多すぎます');
    if (typeof item === 'string') size += new TextEncoder().encode(item).length;
    else if (item && typeof item === 'object') {
      const entries = Object.entries(item);
      if (entries.length + count > 20000) throw new Error('読み込みデータの項目数が多すぎます');
      for (const [key, child] of entries) { size += key.length; stack.push([child, depth + 1]); }
    }
    if (size > ARTICLE_MAX_BYTES) throw new Error('読み込みデータは5MB以下にしてください');
  }
}
function checkArticleFile(file) {
  if (file.size > ARTICLE_MAX_BYTES) throw new Error('読み込みファイルは5MB以下にしてください');
}
function setArticleResource(node, value, attr = 'src', preview = true) {
  const deferred = `data-security-${attr}`;
  const url = safeArticleUrl(value, node.tagName);
  node.removeAttribute(attr);
  node.removeAttribute(deferred);
  if (!url || (node.tagName === 'IFRAME' && attr === 'src' && !trustedArticleFrame(url))) return;
  node.setAttribute(attr, url);
}

function safeArticleUrl(value, tag = 'A') {
  const raw = String(value || '').replace(/[\u0000-\u0020\u007f]/g, '').trim();
  if (!raw) return '';
  if (tag === 'IMG' && /^data:image\/(?:png|gif|jpe?g|webp);base64,[a-z\d+/=]+$/i.test(raw)) return raw;
  if (raw.startsWith('#')) return raw;
  try {
    const url = new URL(raw, 'https://article.invalid/');
    if (url.username || url.password) return '';
    if (['http:', 'https:'].includes(url.protocol)) return raw;
    if (tag === 'A' && ['mailto:', 'tel:'].includes(url.protocol)) return raw;
  } catch {}
  return '';
}

function trustedArticleFrame(value) {
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password || u.port) return false;
    return (u.hostname === 'www.youtube.com' && /^\/embed\/[\w-]+$/.test(u.pathname))
      || (u.hostname === 'player.vimeo.com' && /^\/video\/\d+$/.test(u.pathname))
      || (u.hostname === 'drive.google.com' && /^\/file\/d\/[\w-]+\/preview$/.test(u.pathname))
      || (u.hostname === 'speakerdeck.com' && /^\/player\/[a-f\d]{32}$/i.test(u.pathname))
      || (['www.slideshare.net', 'slideshare.net'].includes(u.hostname) && /^\/slideshow\/embed_code\/(?:key\/[\w-]+|\d+)\/?$/.test(u.pathname));
  } catch { return false; }
}

function sanitizeArticleMarkup(value, { preview = false, depth = 0 } = {}) {
  if (depth > 8) return '';
  if (!window.DOMPurify?.isSupported) throw new Error('安全なHTML処理を利用できません。再読み込みしてください。');
  const input = checkArticleTextSize(value);
  if ((input.match(/</g) || []).length > 40000) throw new Error('HTMLの要素数が多すぎます');
  const root = DOMPurify.sanitize(input, {
    RETURN_DOM: true, USE_PROFILES: { html: true },
    ADD_TAGS: ['iframe', '#comment'], ADD_ATTR: ['contenteditable', 'target', 'allowfullscreen'],
    FORBID_TAGS: ['script', 'style', 'link', 'meta', 'base', 'object', 'embed', 'form', 'input', 'textarea', 'select', 'template'],
    FORBID_ATTR: ['srcdoc', 'srcset', 'background', 'action', 'formaction', 'autofocus', 'is', 'popover', 'ping']
  });
  if (root.querySelectorAll('*').length > 20000) throw new Error('HTMLの要素数が多すぎます');
  for (const node of root.querySelectorAll('*')) {
    let ancestor = node.parentElement, nesting = 0;
    while (ancestor && ancestor !== root) {
      if (++nesting > 128) throw new Error('HTMLの階層が深すぎます');
      ancestor = ancestor.parentElement;
    }
    // A saved article must not shadow editor controls via duplicate IDs/names.
    const existing = node.id && document.getElementById(node.id);
    if (existing && !existing.closest('#preview')) node.removeAttribute('id');
    node.removeAttribute('name');
    for (const attr of Array.from(node.attributes)) {
      if (attr.name.startsWith('data-') && attr.value.includes('<')) {
        node.setAttribute(attr.name, sanitizeArticleMarkup(attr.value, { preview, depth: depth + 1 }));
      }
    }
    if (node.hasAttribute('style')) {
      for (const property of Array.from(node.style)) {
        const v = node.style.getPropertyValue(property);
        // CSS resources and escaped identifiers must not bypass URL controls.
        if (/url\s*\(|image-set\s*\(|expression\s*\(|\\|@/i.test(v)
          || /^(?:behavior|-moz-binding|z-index)$/.test(property)
          || (property === 'position' && /fixed|sticky/i.test(v))) node.style.removeProperty(property);
      }
    }
    for (const attr of ['href', 'src', 'poster', 'background', 'data-security-src', 'data-security-poster']) {
      if (!node.hasAttribute(attr)) continue;
      const clean = safeArticleUrl(node.getAttribute(attr), node.tagName);
      if (clean) node.setAttribute(attr, clean); else node.removeAttribute(attr);
    }
    if (node.tagName === 'IFRAME') {
      if (!trustedArticleFrame(node.getAttribute('data-security-src') || node.getAttribute('src'))) { node.remove(); continue; }
      node.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
      node.setAttribute('referrerpolicy', 'no-referrer');
    }
    if (node.tagName === 'A') node.setAttribute('rel', 'noopener noreferrer');
    if (['IMG', 'IFRAME', 'VIDEO', 'AUDIO', 'SOURCE', 'TRACK'].includes(node.tagName)) {
      node.setAttribute('referrerpolicy', 'no-referrer');
      for (const attr of ['src', 'poster']) {
        const deferred = `data-security-${attr}`;
        const resource = node.getAttribute(deferred) || node.getAttribute(attr);
        if (!resource) continue;
        setArticleResource(node, resource, attr, preview);
      }
    }
  }
  return root.innerHTML;
}

function sanitizeArticleSettings(value, depth = 0) {
  if (depth > 16) return null;
  if (typeof value === 'string') return value.includes('<') ? sanitizeArticleMarkup(value) : value;
  if (Array.isArray(value)) return value.map(item => sanitizeArticleSettings(item, depth + 1));
  if (!value || typeof value !== 'object') return value;
  const result = Object.create(null);
  for (const [key, item] of Object.entries(value)) {
    if (['__proto__', 'constructor', 'prototype'].includes(key)) continue;
    result[key] = sanitizeArticleSettings(item, depth + 1);
  }
  return result;
}
