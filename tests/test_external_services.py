"""Browser checks for external service integration (network replies are deterministic)."""
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright


class ExternalServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel='msedge', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.route('https://**/*', lambda route: route.fulfill(status=200, body=''))
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto((Path(__file__).resolve().parents[1] / 'index.html').as_uri())

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def test_url_validation_and_google_share_parameters(self):
        result = self.page.evaluate("""() => ({
          file: externalDocumentInfo('https://drive.google.com/file/d/test_123/view?resourcekey=key-1&usp=sharing'),
          old: externalDocumentInfo('https://drive.google.com/open?id=test_123'),
          sheet: externalDocumentInfo('https://docs.google.com/spreadsheets/d/test_123/edit#gid=42'),
          slides: externalDocumentInfo('https://docs.google.com/presentation/d/test_123/edit'),
          document: externalDocumentInfo('https://docs.google.com/document/d/test_123/edit'),
          rejected: ['javascript:alert(1)', 'https://drive.google.com.evil.test/file/d/abc/view',
            'https://drive.google.com/drive/folders/abc', 'https://user@drive.google.com/file/d/abc/view',
            'https://speakerdeck.com/player/abcdef', 'https://slideshare.net/api/oembed']
            .map(externalDocumentInfo),
        })""")
        self.assertEqual(result['file']['embedUrl'], 'https://drive.google.com/file/d/test_123/preview?resourcekey=key-1')
        self.assertEqual(result['file']['label'], 'Googleドライブ（PDF）')
        self.assertEqual(result['old']['url'], 'https://drive.google.com/file/d/test_123/view')
        self.assertIsNone(result['sheet'])
        self.assertIsNone(result['slides'])
        self.assertIsNone(result['document'])
        self.assertTrue(all(item is None for item in result['rejected']))

    def test_drive_slide_settings_json_and_html_round_trip(self):
        result = self.page.evaluate("""async () => {
          elements.preview.innerHTML = insertedComponentHtml('document');
          activeInsertedComponent = elements.preview.firstElementChild;
          const properties = document.querySelector('.inserted-component-properties');
          properties._sync();
          const settings = document.querySelector('.document-component-settings');
          const visible = !settings.hidden;
          const layout = {
            groups:Array.from(settings.querySelectorAll(':scope > .list-settings-group > strong'), item => item.textContent),
            serviceNote:settings.querySelector('#documentServiceNote').textContent,
            driveHelpOpen:settings.querySelector('#documentDriveHelp').open
          };
          const set = (id, value) => {
            const input = document.getElementById(id); input.value = value;
            input.dispatchEvent(new Event('input', {bubbles:true}));
          };
          set('documentUrl', 'https://drive.google.com/file/d/test_123/view?resourcekey=key-1');
          set('documentTitle', '設計資料'); set('documentCaption', '共有の説明'); set('documentHeight', '500');
          const before = activeInsertedComponent.innerHTML;
          const exported = formatOutputHtml(getPersistablePreviewHtml());
          const unchanged = before === activeInsertedComponent.innerHTML;
          const payload = JSON.parse(await createArticlePayloadBlob().text());
          applyArticlePayload(payload);
          const jsonPart = elements.preview.querySelector('[data-inserted-component="document"]');
          const json = {url:jsonPart.dataset.documentUrl, frame:jsonPart.querySelector('iframe').src};
          importArticleHtml(exported);
          activeInsertedComponent = elements.preview.querySelector('[data-inserted-component="document"]');
          properties._sync();
          const restored = {title:document.querySelector('#documentTitle').value,
            caption:document.querySelector('#documentCaption').value,
            frame:activeInsertedComponent.querySelector('iframe').src};
          return {visible, layout, unchanged, exported, json, restored,
            hasDocumentConversion:!!document.querySelector('#documentToLinkCard'),
            hasLinkCardConversion:!!document.querySelector('#linkCardToDocument')};
        }""")
        self.assertTrue(result['visible'])
        self.assertEqual(result['layout']['groups'], ['スライドURL', '表示テキスト', 'プレビュー'])
        self.assertIn('Googleドライブ上のPDF', result['layout']['serviceNote'])
        self.assertFalse(result['layout']['driveHelpOpen'])
        self.assertTrue(result['unchanged'])
        self.assertNotIn('<iframe', result['exported'])
        self.assertNotIn('プレビュー取得', result['exported'])
        self.assertIn('resourcekey=key-1', result['json']['frame'])
        self.assertEqual(result['restored']['title'], '設計資料')
        self.assertEqual(result['restored']['caption'], '共有の説明')
        self.assertFalse(result['hasDocumentConversion'])
        self.assertFalse(result['hasLinkCardConversion'])

    def test_publication_embeds_are_explicit_links_in_every_output_mode(self):
        results = self.page.evaluate("""() => {
          const samples = [
            ['document', 'https://speakerdeck.com/demo/deck'],
            ['document', 'https://www.slideshare.net/demo/deck'],
            ['document', 'https://drive.google.com/file/d/abc/view?resourcekey=key-1'],
            ['video', 'https://youtu.be/abcdefghijk'],
            ['video', 'https://vimeo.com/123456']
          ];
          const results = [];
          for (const mode of ['pretty', 'compact', 'noComments']) {
            elements.htmlOutputMode.value = mode;
            for (const [type, url] of samples) {
              const holder = document.createElement('div');
              holder.innerHTML = insertedComponentHtml(type);
              holder.firstElementChild.dataset[type === 'video' ? 'embedUrl' : 'documentUrl'] = url;
              const source = '<section><div><p>本文</p>' + holder.innerHTML + '</div></section>';
              const output = formatOutputHtml(source);
              const html = document.createElement('div');
              html.innerHTML = output;
              const link = html.querySelector('a');
              const rendered = document.createElement('div');
              rendered.innerHTML = marked.parse(output);
              // ProtoPedia enumerates anchors and submits their text, not href, to oEmbed.
              const resolvedUrls = [...rendered.querySelectorAll('a')].map(a => a.textContent);
              results.push({mode, type, url, href:link?.getAttribute('href'), text:link?.textContent,
                resolvedUrls, frame:!!html.querySelector('iframe'), script:!!html.querySelector('script')});
            }
          }
          return results;
        }""")
        for item in results:
            with self.subTest(mode=item['mode'], type=item['type'], url=item['url']):
                self.assertEqual(item['href'], item['url'])
                self.assertEqual(item['text'], item['url'])
                self.assertEqual(item['resolvedUrls'], [item['url']])
                self.assertFalse(item['frame'])
                self.assertFalse(item['script'])

    def test_video_captions_survive_explicit_link_export_and_import(self):
        results = self.page.evaluate("""() => {
          const results = [];
          for (const url of ['https://youtu.be/abcdefghijk']) {
            for (const mode of ['pretty', 'compact']) {
              elements.htmlOutputMode.value = mode;
              elements.preview.innerHTML = insertedComponentHtml('video');
              const video = elements.preview.firstElementChild;
              Object.assign(video.dataset, {embedUrl:url, videoBottomText:'動画の説明', videoBottomHtml:'<em>動画の説明</em>'});
              renderEmbedComponent(video);
              const before = video.innerHTML;
              const output = formatOutputHtml(getPersistablePreviewHtml());
              const unchanged = before === video.innerHTML;
              importArticleHtml(output);
              const restored = elements.preview.querySelector('[data-inserted-component="video"]');
              results.push({url, mode, unchanged, restoredUrl:restored.dataset.embedUrl,
                caption:restored.dataset.videoBottomHtml,
                captionCount:elements.preview.querySelectorAll('[data-video-bottom-text]:not([data-inserted-component])').length});
            }
          }
          return results;
        }""")
        for item in results:
            with self.subTest(url=item['url'], mode=item['mode']):
                self.assertTrue(item['unchanged'])
                self.assertEqual(item['restoredUrl'], item['url'])
                self.assertEqual(item['caption'], '<em>動画の説明</em>')
                self.assertEqual(item['captionCount'], 1)

    def test_slide_preview_fetch_and_untrusted_code(self):
        result = self.page.evaluate("""async () => {
          const originalFetch = window.fetch;
          try {
            const results = [];
            for (const [url, src] of [
              ['https://speakerdeck.com/demo/deck', 'https://speakerdeck.com/player/0123456789abcdef0123456789abcdef'],
              ['https://www.slideshare.net/slideshow/demo/12345', 'https://www.slideshare.net/slideshow/embed_code/key/abcd']]) {
              elements.preview.innerHTML = insertedComponentHtml('document');
              const component = elements.preview.firstElementChild;
              component.dataset.documentUrl = url;
              window.fetch = async () => ({ok:true, json:async () => ({title:'資料名',
                html:'<iframe src="' + src + '" onload="window.badEmbed=true"></iframe><script>window.badEmbed=true;<\\/script>'})});
              const ok = await resolveDocumentPreview(component);
              const exported = formatOutputHtml(getPersistablePreviewHtml());
              importArticleHtml(exported);
              const restored = elements.preview.querySelector('[data-inserted-component="document"]');
              results.push({ok, src:restored.querySelector('iframe').src, title:restored.dataset.documentTitle,
                unsafe:!!restored.querySelector('script,[onload]'), exportFrame:exported.includes('<iframe')});
            }
            const unsafe = documentEmbedFromCode('<iframe src="https://evil.test/player"></iframe>', 'speakerdeck');
            window.fetch = async () => { throw new Error('offline'); };
            const failed = await resolveDocumentPreview(elements.preview.querySelector('[data-inserted-component="document"]'));
            return {results, unsafe, executed:!!window.badEmbed, failed};
          } finally { window.fetch = originalFetch; }
        }""")
        for item in result['results']:
            self.assertTrue(item['ok'])
            self.assertEqual(item['title'], '資料名')
            self.assertFalse(item['unsafe'])
            self.assertFalse(item['exportFrame'])
        self.assertFalse(result['executed'])
        self.assertFalse(result['failed'])
        self.assertEqual(result['unsafe'], '')

    def test_github_url_remains_an_ordinary_link_card(self):
        result = self.page.evaluate("""async () => {
          const originalFetch = window.fetch;
          try {
            elements.preview.innerHTML = insertedComponentHtml('linkCard');
            activeInsertedComponent = elements.preview.firstElementChild;
            document.querySelector('.inserted-component-properties')._sync();
            let fetchCount = 0;
            window.fetch = async () => { fetchCount += 1; throw new Error('unexpected fetch'); };
            const input = document.querySelector('#linkCardUrl');
            input.value = 'https://github.com/demo/project';
            input.dispatchEvent(new Event('input', {bubbles:true}));
            input.dispatchEvent(new Event('change', {bubbles:true}));
            await new Promise(resolve => setTimeout(resolve, 0));
            const component = elements.preview.firstElementChild;
            return {
              fetchCount,
              url:component.dataset.linkCardUrl,
              title:component.querySelector('[data-link-card-title]').textContent,
              hasButton:Boolean(document.querySelector('#linkCardFetchGithub')),
              hasFunction:typeof fetchGithubLinkCard !== 'undefined'
            };
          } finally { window.fetch = originalFetch; }
        }""")
        self.assertEqual(result['fetchCount'], 0)
        self.assertEqual(result['url'], 'https://github.com/demo/project')
        self.assertEqual(result['title'], 'リンク先のタイトル')
        self.assertFalse(result['hasButton'])
        self.assertFalse(result['hasFunction'])

    def test_plain_document_urls_recover_without_converting_link_cards(self):
        result = self.page.evaluate("""() => {
          const holder = document.createElement('div');
          holder.innerHTML = insertedComponentHtml('linkCard');
          const card = holder.firstElementChild;
          const url = 'https://drive.google.com/file/d/abc/view';
          card.dataset.linkCardUrl = url;
          card.querySelector('a').href = url;
          card.querySelector('[data-link-card-title]').textContent = url;
          importArticleHtml('<p>https://speakerdeck.com/demo/deck</p><p>' + url + '</p>' + card.outerHTML);
          return {documents:elements.preview.querySelectorAll('[data-inserted-component="document"]').length,
            cards:elements.preview.querySelectorAll('[data-inserted-component="linkCard"]').length};
        }""")
        self.assertEqual(result, {'documents':2, 'cards':1})
