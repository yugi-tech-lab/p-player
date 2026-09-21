"""Regression checks for hostile saved articles, with all external traffic blocked."""
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        cls.browser = cls.p.chromium.launch(channel='msedge', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.requests = []
        def block(route):
            self.requests.append(route.request.url)
            route.abort()
        self.page.route('https://**/*', block)
        self.page.goto((Path(__file__).resolve().parents[1] / 'index.html').as_uri())

    def tearDown(self):
        self.page.close()

    def test_json_html_metadata_and_autosave_cannot_execute(self):
        for mode in ['json', 'html', 'autosave']:
            with self.subTest(mode=mode):
                self.page.evaluate('''mode => {
                  window.securityProbe = 0;
                  const attack = '<img src="bad" onerror="window.securityProbe++">';
                  const holder = document.createElement('template');
                  holder.innerHTML = insertedComponentHtml('video');
                  holder.content.firstElementChild.dataset.videoBottomHtml = attack;
                  holder.content.firstElementChild.dataset.embedUrl = 'https://vimeo.com/123456';
                  const html = '<p>test</p>' + attack + holder.innerHTML;
                  if (mode === 'json') applyArticlePayload({saveType:'full', settings:{}, articleHtml:html});
                  if (mode === 'html') importArticleHtml(html);
                  if (mode === 'autosave') restoreAutosavePayload({settings:{},previewHtml:html}, 'test');
                  elements.preview.querySelectorAll('[data-inserted-component="video"]').forEach(renderEmbedComponent);
                  const exported = formatOutputHtml(getPersistablePreviewHtml());
                  window.securityExport = sanitizeArticleMarkup(exported);
                }''', mode)
                self.page.wait_for_timeout(100)
                self.assertEqual(self.page.evaluate('window.securityProbe'), 0)
                self.assertEqual(self.page.locator('#preview [onerror]').count(), 0)
                self.assertNotIn('onerror', self.page.evaluate('window.securityExport'))

    def test_import_loads_external_content_without_prompt_and_preserves_urls(self):
        result = self.page.evaluate('''() => {
          importArticleHtml('<p>test</p><img src="https://audit.invalid/pixel">'
            + '<div style="background-image:url(https://audit.invalid/css)">test</div>'
            + '<iframe src="https://www.youtube.com/embed/abcdefghijk"></iframe>');
          return {src:elements.preview.querySelector('img').getAttribute('src'),
            deferred:elements.preview.querySelector('img').dataset.securitySrc,
            exported:formatOutputHtml(getPersistablePreviewHtml())};
        }''')
        self.page.wait_for_timeout(150)
        self.assertEqual(result['src'], 'https://audit.invalid/pixel')
        self.assertIsNone(result['deferred'])
        self.assertIn('src="https://audit.invalid/pixel"', result['exported'])
        self.assertEqual(self.page.locator('#articleExternalContentNotice').count(), 0)
        self.assertNotIn('https://audit.invalid/css', self.requests)
        self.assertIn('https://audit.invalid/pixel', self.requests)

    def test_styles_urls_and_duplicate_editor_ids_are_restricted(self):
        result = self.page.evaluate('''() => {
          const original = elements.preview;
          importArticleHtml('<div id="videoUrl" style="position:fixed;inset:0;z-index:2147483647">test</div>'
            + '<a href="&#1;javascript:alert(1)">bad link</a>'
            + '<svg onload="window.securityProbe=1"></svg>');
          return {position:original.firstElementChild.style.position,
            fixed:original.querySelectorAll('[style*="fixed"]').length,
            collision:original.querySelectorAll('#videoUrl').length,
            href:original.querySelector('a').getAttribute('href'),
            contain:getComputedStyle(original).contain};
        }''')
        self.assertEqual(result['fixed'], 0)
        self.assertEqual(result['collision'], 0)
        self.assertIsNone(result['href'])
        self.assertIn('paint', result['contain'])

    def test_auto_loading_survives_markdown_and_card_edits(self):
        result = self.page.evaluate('''() => {
          importArticleHtml('<table background="https://audit.invalid/background"><tr><td>test</td></tr></table>');
          importMarkdownText('![test](https://audit.invalid/markdown)');
          const markdownUrl = elements.preview.querySelector('img').getAttribute('src');
          const markdownExport = formatOutputHtml(getPersistablePreviewHtml());
          const t = document.createElement('template');
          t.innerHTML = insertedComponentHtml('linkCard');
          Object.assign(t.content.firstElementChild.dataset, {
            linkCardShowImage:'true', linkCardImageUrl:'https://audit.invalid/card'
          });
          importArticleHtml(t.innerHTML);
          activeInsertedComponent = elements.preview.querySelector('[data-inserted-component="linkCard"]');
          document.querySelector('.inserted-component-properties')._sync();
          const control = document.querySelector('#linkCardRadius');
          control.value = '12'; control.dispatchEvent(new Event('input', {bubbles:true}));
          return {markdownUrl, markdownExport, cardUrl:activeInsertedComponent.querySelector('img').getAttribute('src')};
        }''')
        self.page.wait_for_timeout(150)
        self.assertNotIn('https://audit.invalid/background', self.requests)
        self.assertIn('https://audit.invalid/markdown', self.requests)
        self.assertIn('https://audit.invalid/card', self.requests)
        self.assertEqual(result['markdownUrl'], 'https://audit.invalid/markdown')
        self.assertIn('https://audit.invalid/markdown', result['markdownExport'])
        self.assertEqual(result['cardUrl'], 'https://audit.invalid/card')

    def test_effective_iframe_url_must_be_trusted(self):
        result = self.page.evaluate('''() => {
          const input = '<iframe src="https://www.youtube.com/embed/abcdefghijk" data-security-src="https://audit.invalid/frame"></iframe>';
          return [true,false].map(preview => sanitizeArticleMarkup(input, {preview}));
        }''')
        self.assertTrue(all('<iframe' not in html for html in result))

    def test_import_limits_preserve_current_article(self):
        result = self.page.evaluate('''() => {
          elements.preview.innerHTML = '<p>keep my work</p>';
          const before = elements.preview.innerHTML;
          const outcomes = [];
          const big = 'x'.repeat(5 * 1024 * 1024 + 1);
          for (const run of [
            () => importArticleHtml(big),
            () => importMarkdownText(big),
            () => applyArticlePayload({saveType:'full',settings:{},articleHtml:big}),
            () => restoreAutosavePayload({previewHtml:big}, 'test'),
            () => applyArticlePayload({saveType:'full',settings:{},articleHtml:'<br>'.repeat(20001)}),
            () => importArticleHtml('<div>'.repeat(150)+'test'+'</div>'.repeat(150)),
            () => checkArticleFile({size:big.length})
          ]) {
            let rejected = false;
            try { run(); } catch { rejected = true; }
            outcomes.push({rejected, intact:elements.preview.innerHTML === before});
          }
          return outcomes;
        }''')
        self.assertTrue(all(item['rejected'] and item['intact'] for item in result))
