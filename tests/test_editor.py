"""Browser regression tests: pip install playwright; python -m unittest discover -s tests -v.

Uses an installed Microsoft Edge browser (no browser download required).
"""
import json
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="msedge", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto((Path(__file__).resolve().parents[1] / "index.html").as_uri())

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def test_startup(self):
        self.assertGreater(self.page.evaluate("elements.preview.children.length"), 0)

    def test_header_shows_automatic_last_updated_date(self):
        result = self.page.evaluate("""() => {
            const label = document.querySelector('#lastUpdated');
            return {
              hidden: label.hidden,
              text: label.textContent,
              dateTime: label.dateTime,
              knownDate: formatLastUpdatedDate('2026-09-20T12:34:56'),
              invalidDate: formatLastUpdatedDate('not-a-date')
            };
        }""")
        self.assertFalse(result['hidden'])
        self.assertRegex(result['text'], r'^最終更新 \d{4}\.\d{2}\.\d{2}$')
        self.assertRegex(result['dateTime'], r'^\d{4}-\d{2}-\d{2}$')
        self.assertEqual(result['knownDate'], '2026.09.20')
        self.assertEqual(result['invalidDate'], '')

    def test_image_text_bubble_tail_is_visible_on_first_enable(self):
        for side in ('left', 'right'):
            for existing_tail in (False, True):
                result = self.page.evaluate("""({side, existingTail}) => {
                    elements.preview.innerHTML = insertedComponentHtml('imageText');
                    const component = elements.preview.firstElementChild;
                    component.style.flexDirection = side === 'right' ? 'row-reverse' : 'row';
                    if (existingTail) component.children[1].insertAdjacentHTML('afterbegin',
                        '<span data-speech-tail="true" contenteditable="false"></span>');
                    activeInsertedComponent = component;
                    document.querySelector('.inserted-component-properties')._sync();
                    document.querySelector('#componentSpeechBubble').click();
                    const tail = component.querySelector('[data-speech-tail]');
                    const rect = tail.getBoundingClientRect();
                    const initial = tail.style.cssText;
                    const border = getComputedStyle(tail).borderLeftWidth;
                    elements.speechBubbleTailAngle.dispatchEvent(new Event('input', {bubbles:true}));
                    const unchanged = initial === tail.style.cssText;
                    cleanupEmptyFormattingSpans();
                    const preserved = component.contains(tail);
                    document.querySelector('#componentSpeechBubble').click();
                    const removed = !component.querySelector('[data-speech-tail]');
                    document.querySelector('#componentSpeechBubble').click();
                    return {width: rect.width, height: rect.height, border, unchanged, preserved, removed,
                        restored: !!component.querySelector('[data-speech-tail]')};
                }""", {'side': side, 'existingTail': existing_tail})
                self.assertGreater(result['width'], 0)
                self.assertGreater(result['height'], 0)
                self.assertEqual(result['border'], '2px')
                for key in ('unchanged', 'preserved', 'removed', 'restored'):
                    self.assertTrue(result[key], key)

    def test_character_count_at_right_of_format_row(self):
        for width in (1440, 600):
            self.page.set_viewport_size({"width": width, "height": 900})
            result = self.page.evaluate("""() => {
                const counter = document.querySelector('#characterCount');
                const controls = document.querySelector('.selection-controls');
                const format = controls.querySelector('.selection-format-row-content');
                const rect = counter.getBoundingClientRect();
                const row = controls.getBoundingClientRect();
                const content = format.getBoundingClientRect();
                elements.preview.innerHTML = '<p>あいう ABC</p>';
                updateCharacterCount();
                return {parent: counter.parentElement === controls,
                    right: Math.abs(rect.right - row.right),
                    sameRow: rect.top < content.bottom && rect.bottom > content.top,
                    noOverlap: rect.left >= content.right,
                    text: counter.textContent};
            }""")
            self.assertTrue(result['parent'])
            self.assertLess(result['right'], 2)
            self.assertTrue(result['sameRow'])
            self.assertTrue(result['noOverlap'])
            self.assertEqual(result['text'], '文字数 6')

    def test_shape_settings_render_and_survive_html_import(self):
        result = self.page.evaluate("""() => {
            elements.preview.replaceChildren(); capturePreviewEdits();
            activeInsertedComponent = null; savedPreviewRange = null;
            insertComponentAtSelection('shape');
            const shape = elements.preview.querySelector('[data-inserted-component="shape"]');
            activeInsertedComponent = shape;
            document.querySelector('.inserted-component-properties')._sync();
            document.querySelector('#shapeColor').closest('.color-row').querySelector('[aria-label="青"]').click();
            const paletteColor = shape.dataset.shapeColor;
            for (const [id, value] of Object.entries({shapeKind:'triangleDown',shapeColor:'#ff0000',shapeWidth:'80',shapeHeight:'40',shapeAlign:'right',shapeGap:'20'})) {
              const control = document.getElementById(id);
              control.value = value;
              control.dispatchEvent(new Event('input', {bubbles:true}));
            }
            const visual = shape.querySelector('[data-shape-visual]');
            const rect = visual.getBoundingClientRect();
            const html = formatOutputHtml(getPersistablePreviewHtml());
            const imported = importArticleHtml(html);
            const restored = elements.preview.querySelector('[data-inserted-component="shape"]');
            return {width:rect.width,height:rect.height,imported,paletteColor,
              kind:restored.dataset.shapeKind,color:restored.dataset.shapeColor,
              align:restored.style.textAlign, gap:restored.style.marginTop};
        }""")
        self.assertEqual(result['width'], 80)
        self.assertEqual(result['paletteColor'], '#0000ff')
        self.assertEqual(result['height'], 40)
        self.assertTrue(result['imported'])
        self.assertEqual(result['kind'], 'triangleDown')
        self.assertEqual(result['color'], '#ff0000')
        self.assertEqual(result['align'], 'right')
        self.assertEqual(result['gap'], '20px')

    def test_shape_export_survives_removal_of_css_and_editor_attributes(self):
        result = self.page.evaluate("""() => {
            const kinds = ['arrowDown','arrowUp','arrowRight','arrowLeft','triangleDown','triangleUp','triangleRight','triangleLeft'];
            return kinds.map(kind => {
              const holder = document.createElement('div');
              holder.innerHTML = shapeComponentHtml();
              holder.firstElementChild.dataset.shapeKind = kind;
              const html = formatOutputHtml(holder.innerHTML);
              holder.innerHTML = html;
              const visual = holder.querySelector('[data-shape-visual]');
              const noAdvancedCss = !html.includes('clip-path') && !html.includes('aspect-ratio');
              holder.querySelectorAll('*').forEach(el => [...el.attributes].forEach(attr => el.removeAttribute(attr.name)));
              return {text:holder.textContent.trim(),noAdvancedCss};
            });
        }""")
        self.assertEqual([entry['text'] for entry in result], ['↓','↑','→','←','▼','▲','▶','◀'])
        self.assertTrue(all(entry['noAdvancedCss'] for entry in result))

    def test_copy_html_keeps_shape_preview_and_history_unchanged(self):
        result = self.page.evaluate("""async () => {
            elements.preview.innerHTML = shapeComponentHtml();
            capturePreviewEdits();
            const before = elements.preview.innerHTML;
            const historyCount = previewHistory.length;
            let copied = '';
            Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{writeText:async text => {copied = text;}}});
            await copyGeneratedHtml();
            await copyGeneratedHtml();
            const visual = elements.preview.querySelector('[data-shape-visual]');
            return {unchanged:elements.preview.innerHTML === before,
              visible:!!visual && visual.getBoundingClientRect().height > 0,
              sameHistory:previewHistory.length === historyCount,
              copied:copied.includes('↓')};
        }""")
        self.assertEqual(result, dict(unchanged=True, visible=True, sameHistory=True, copied=True))

    def test_ime_confirmation_does_not_insert_newline_and_undo_is_atomic(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>start</p>'; capturePreviewEdits();
            const p = elements.preview.querySelector('p');
            p.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}));
            for (const text of ['に', 'にほん', '日本']) {
              p.textContent = 'start' + text;
              p.dispatchEvent(new InputEvent('input', {bubbles:true, isComposing:true, inputType:'insertCompositionText'}));
            }
            const enter = new KeyboardEvent('keydown', {key:'Enter', isComposing:true, bubbles:true, cancelable:true});
            p.dispatchEvent(enter);
            p.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true, data:'日本'}));
            performPreviewUndo();
            const undone = elements.preview.textContent;
            performPreviewRedo();
            return {prevented:enter.defaultPrevented, undone, redone:elements.preview.textContent};
        }""")
        self.assertEqual(result, {'prevented': False, 'undone': 'start', 'redone': 'start日本'})

    def test_unsaved_state_save_failure_success_and_cancel_open(self):
        result = self.page.evaluate("""async () => {
            elements.preview.innerHTML = '<p>saved</p>'; capturePreviewEdits(); markArticleSaved();
            elements.preview.innerHTML = '<p>changed</p>'; capturePreviewEdits();
            const dirty = articleHasUnsavedChanges();
            window.confirm = () => false;
            let opened = false;
            window.showOpenFilePicker = async () => { opened = true; return []; };
            document.querySelector('#importJsonButton').click();
            await Promise.resolve();
            const close = new Event('beforeunload', {cancelable:true});
            window.dispatchEvent(close);
            try { await writeArticleFile({createWritable:async () => {throw new Error('denied');}}); } catch {}
            const afterFailure = articleHasUnsavedChanges();
            await writeArticleFile({createWritable:async () => ({write:async () => {},close:async () => {}})});
            const afterSuccess = articleHasUnsavedChanges();
            performPreviewUndo();
            const afterUndo = articleHasUnsavedChanges();
            performPreviewRedo();
            return {dirty, opened, closePrevented:close.defaultPrevented, afterFailure, afterSuccess, afterUndo, afterRedo:articleHasUnsavedChanges()};
        }""")
        self.assertEqual(result, dict(dirty=True, opened=False, closePrevented=True,
                                     afterFailure=True, afterSuccess=False, afterUndo=True, afterRedo=False))

    def test_all_parts_json_and_html_round_trip(self):
        types = ['heading', 'body', 'list', 'note', 'quote', 'qa', 'table', 'image', 'imageText', 'imagePair',
                 'beforeAfter', 'code', 'rule', 'xpost', 'video', 'accordion', 'linkCard', 'toc', 'shape']
        result = self.page.evaluate("""async types => {
            window.twttr = {widgets:{load:() => {}}};
            const results = [];
            for (const type of types) {
              const holder = document.createElement('div');
              if (['heading', 'body'].includes(type)) {
                const fragment = document.createDocumentFragment();
                fragment.append('Round trip text');
                holder.append(createDocumentBlockFromFragment(type, fragment, readDocumentBlockSettings(type)));
              } else holder.innerHTML = insertedComponentHtml(type);
              const component = holder.firstElementChild;
              if (type === 'xpost') component.dataset.embedUrl = 'https://x.com/test/status/123';
              if (type === 'video') component.dataset.embedUrl = 'https://youtu.be/abcdefghijk';
              elements.preview.replaceChildren(component);
              capturePreviewEdits();
              const payload = JSON.parse(await createArticlePayloadBlob().text());
              applyArticlePayload(payload);
              const jsonPart = elements.preview.querySelector(`[data-inserted-component="${type}"]`);
              const jsonText = jsonPart?.textContent;
              const exported = formatOutputHtml(getPersistablePreviewHtml());
              importArticleHtml(exported);
              const htmlPart = elements.preview.querySelector(`[data-inserted-component="${type}"]`);
              results.push({type, json:!!jsonPart, html:!!htmlPart,
                textKept: ['xpost','video','toc'].includes(type) || htmlPart?.textContent.replace(/\\s/g, '') === jsonText?.replace(/\\s/g, '')});
            }
            return results;
        }""", types)
        for entry in result:
            with self.subTest(part=entry['type']):
                self.assertTrue(entry['json'])
                self.assertTrue(entry['html'])
                self.assertTrue(entry['textKept'])

    def test_only_desktop_controls_use_an_independent_scroll_pane(self):
        self.page.set_viewport_size({"width": 1280, "height": 720})
        before = self.page.evaluate("""() => {
            const controls = document.querySelector('.controls');
            const previewColumn = document.querySelector('.layout > div:last-child');
            return {
              controlsOverflow: getComputedStyle(controls).overflowY,
              previewOverflow: getComputedStyle(previewColumn).overflowY,
              controlsCanScroll: controls.scrollHeight > controls.clientHeight,
              windowY: window.scrollY
            };
        }""")
        self.page.locator(".controls").hover()
        self.page.mouse.wheel(0, 500)
        self.page.wait_for_timeout(100)
        after = self.page.evaluate("""() => ({
            controlsY: document.querySelector('.controls').scrollTop,
            previewY: document.querySelector('.layout > div:last-child').scrollTop,
            windowY: window.scrollY
        })""")
        self.assertEqual(before["controlsOverflow"], "auto")
        self.assertEqual(before["previewOverflow"], "visible")
        self.assertTrue(before["controlsCanScroll"])
        self.assertEqual(before["windowY"], 0)
        self.assertGreater(after["controlsY"], 0)
        self.assertEqual(after["previewY"], 0)
        self.assertEqual(after["windowY"], 0)

        self.page.locator(".preview").hover()
        self.page.mouse.wheel(0, 500)
        self.page.wait_for_timeout(100)
        preview_scroll = self.page.evaluate("""() => ({
            previewY: document.querySelector('.layout > div:last-child').scrollTop,
            windowY: window.scrollY
        })""")
        self.assertEqual(preview_scroll["previewY"], 0)
        self.assertGreater(preview_scroll["windowY"], 0)

        self.page.set_viewport_size({"width": 800, "height": 720})
        mobile = self.page.evaluate("""() => ({
            bodyOverflow: getComputedStyle(document.body).overflowY,
            controlsOverflow: getComputedStyle(document.querySelector('.controls')).overflowY
        })""")
        self.assertEqual(mobile["bodyOverflow"], "visible")
        self.assertEqual(mobile["controlsOverflow"], "visible")

    def test_unicode_search_offsets(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>\\u0130X</p>';
            document.querySelector('#previewSearchText').value = 'X';
            navigatePreviewSearch(1);
            return window.getSelection().toString();
        }""")
        self.assertEqual(result, "X")

    def test_replace_all_excludes_style_and_script(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>target</p><style>/* target */</style><script>/* target */<\\/script>';
            document.querySelector('#previewSearchText').value = 'target';
            document.querySelector('#previewReplaceText').value = 'changed';
            replaceAllPreviewMatches();
            return [...elements.preview.querySelectorAll('p,style,script')].map(el => el.textContent);
        }""")
        self.assertEqual(result, ["changed", "/* target */", "/* target */"])

    def test_undo_redo_schedule_autosave(self):
        self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>first</p>'; capturePreviewEdits();
            elements.preview.innerHTML = '<p>second</p>'; capturePreviewEdits();
            performAutosave(); performPreviewUndo();
        }""")
        self.page.wait_for_function("JSON.parse(localStorage.getItem(AUTOSAVE_STORAGE_KEY)).previewHtml.includes('first')", timeout=6000)
        self.page.evaluate("performPreviewRedo()")
        self.page.wait_for_function("JSON.parse(localStorage.getItem(AUTOSAVE_STORAGE_KEY)).previewHtml.includes('second')", timeout=6000)

    def test_rendered_changes_are_undoable_and_redo_survives_capture(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>before</p>'; capturePreviewEdits();
            formattedPreviewHtml = '<p>after</p>';
            render({forceReset:true});
            performPreviewUndo();
            const undone = elements.preview.textContent;
            capturePreviewEdits();
            const canRedo = !document.querySelector('#redoButton').disabled;
            performPreviewRedo();
            return {undone, canRedo, redone:elements.preview.textContent};
        }""")
        self.assertEqual(result, {"undone": "before", "canRedo": True, "redone": "after"})

    def test_continuous_typing_uses_one_undo_step(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>before</p>'; capturePreviewEdits();
            const beforeCount = previewHistory.length;
            const paragraph = elements.preview.querySelector('p');
            for (let i = 0; i < 70; i++) {
              paragraph.append('a');
              paragraph.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:'a'}));
            }
            const added = previewHistory.length - beforeCount;
            performPreviewUndo();
            const undone = elements.preview.textContent;
            performPreviewRedo();
            return {added, undone, redone:elements.preview.textContent};
        }""")
        self.assertEqual(result['added'], 1)
        self.assertEqual(result['undone'], 'before')
        self.assertEqual(result['redone'], 'before' + 'a' * 70)

    def test_design_reset_does_not_discard_undo_history(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>keep this article</p>'; capturePreviewEdits();
            resetFormattedPreview();
            render();
            const changed = elements.preview.textContent;
            performPreviewUndo();
            const undone = elements.preview.textContent;
            performPreviewRedo();
            return {changed, undone, redone:elements.preview.textContent};
        }""")
        self.assertEqual(result['undone'], 'keep this article')
        self.assertEqual(result['redone'], result['changed'])

    def test_restore_can_be_undone_and_redone(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>original</p>'; capturePreviewEdits();
            restoreAutosavePayload({settings: collectSettings(), previewHtml: '<p>restored</p>'}, 'restored');
            performPreviewUndo();
            const undone = elements.preview.textContent;
            performPreviewRedo();
            return [undone, elements.preview.textContent];
        }""")
        self.assertEqual(result, ["original", "restored"])

    def test_empty_article_json_replaces_current_article(self):
        self.page.locator('#jsonFileInput').set_input_files({
            "name": "empty.json", "mimeType": "application/json",
            "buffer": json.dumps({"saveType": "full", "articleHtml": ""}).encode(),
        })
        self.page.wait_for_function("jsonFileInput.value === ''")
        self.assertEqual(self.page.evaluate("elements.preview.innerHTML"), "")
        self.assertIn("empty.json", self.page.locator('#activeArticleFilePath').text_content())
        self.assertTrue(self.page.locator('#overwriteJsonButton').is_disabled())

    def test_opened_article_can_be_overwritten_and_shows_its_file(self):
        payload = json.dumps({"saveType": "full", "articleHtml": "<p>opened article</p>"})
        self.page.evaluate("""payload => {
            window.__articleWrites = [];
            const handle = {
              name: 'opened-article.json',
              getFile: async () => ({name: 'opened-article.json', text: async () => payload}),
              createWritable: async () => ({
                write: async blob => window.__articleWrites.push(await blob.text()),
                close: async () => {}
              })
            };
            window.showOpenFilePicker = async () => [handle];
        }""", payload)
        self.page.evaluate("document.querySelector('#importJsonButton').click()")
        self.page.wait_for_function("!document.querySelector('#overwriteJsonButton').disabled")
        self.assertIn("opened-article.json", self.page.locator('#activeArticleFilePath').text_content())
        self.assertEqual(
            self.page.evaluate("document.querySelector('#activeArticleFilePath').parentElement.className"),
            "preview-heading-row",
        )
        self.assertEqual(self.page.evaluate("elements.preview.textContent"), "opened article")

        self.page.evaluate("document.querySelector('#overwriteJsonButton').click()")
        self.page.wait_for_function("window.__articleWrites.length === 1")
        written = self.page.evaluate("JSON.parse(window.__articleWrites[0])")
        self.assertEqual(written["saveType"], "full")
        self.assertIn("opened article", written["articleHtml"])

        self.page.evaluate("window.confirm = () => true; document.querySelector('#resetButton').click()")
        self.assertTrue(self.page.locator('#overwriteJsonButton').is_disabled())
        self.assertTrue(self.page.locator('#activeArticleFilePath').is_hidden())

    def test_pending_edits_saved_on_pagehide(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = '<p>last edit</p>'; capturePreviewEdits();
            window.dispatchEvent(new Event('pagehide'));
            return JSON.parse(localStorage.getItem(AUTOSAVE_STORAGE_KEY))?.previewHtml;
        }""")
        self.assertIn("last edit", result or "")

    def test_json_import_can_be_undone_and_redone(self):
        self.page.evaluate("elements.preview.innerHTML = '<p>original</p>'; capturePreviewEdits();")
        self.page.locator('#jsonFileInput').set_input_files({
            "name": "article.json", "mimeType": "application/json",
            "buffer": json.dumps({"saveType": "full", "articleHtml": "<p>imported</p>"}).encode(),
        })
        self.page.wait_for_function("jsonFileInput.value === ''")
        self.page.evaluate("performPreviewUndo()")
        self.assertEqual(self.page.evaluate("elements.preview.textContent"), "original")
        self.page.evaluate("performPreviewRedo()")
        self.assertEqual(self.page.evaluate("elements.preview.textContent"), "imported")

    def test_exported_html_can_be_reimported_for_best_effort_editing(self):
        exported = self.page.evaluate("""() => {
            const body = elements.preview.querySelector('[data-inserted-component="body"]');
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('note') + insertedComponentHtml('toc');
            body.append(...holder.children);
            capturePreviewEdits();
            return formatOutputHtml(getPersistablePreviewHtml())
              + '<script>window.__unsafeImport = true<\\/script>'
              + '<img src="javascript:alert(1)" onerror="window.__unsafeImport = true">';
        }""")
        self.page.evaluate("""html => {
            window.confirm = () => true;
            document.querySelector('#importHtmlButton').click();
            const pasteMode = document.querySelector('input[name="htmlImportMode"][value="paste"]');
            pasteMode.checked = true;
            pasteMode.dispatchEvent(new Event('change', {bubbles: true}));
            document.querySelector('#htmlPasteText').value = html;
            document.querySelector('#htmlImportConfirmButton').click();
        }""", exported)
        self.page.wait_for_function("!document.querySelector('#htmlImportDialog').open")
        result = self.page.evaluate("""() => ({
            buttonInFileMenu: Boolean(document.querySelector('[data-file-actions="article"] #importHtmlButton')),
            noteEditable: elements.preview.querySelector('[data-inserted-component="note"]')?.contentEditable,
            tocRefresh: Boolean(elements.preview.querySelector('[data-inserted-component="toc"] [data-toc-refresh]')),
            headingEditable: elements.preview.querySelector('[data-heading-content]')?.contentEditable,
            bodyEditable: elements.preview.querySelector('[data-inserted-component="body"]')?.contentEditable,
            scripts: elements.preview.querySelectorAll('script').length,
            unsafeAttributes: elements.preview.querySelectorAll('[onerror],[src^="javascript:"]').length,
            unsafeRan: window.__unsafeImport === true,
            fileLabel: document.querySelector('#activeArticleFilePath').textContent,
            overwriteDisabled: document.querySelector('#overwriteJsonButton').disabled
        })""")
        self.assertTrue(result["buttonInFileMenu"])
        self.assertEqual(result["noteEditable"], "true")
        self.assertTrue(result["tocRefresh"])
        self.assertEqual(result["headingEditable"], "true")
        self.assertEqual(result["bodyEditable"], "true")
        self.assertEqual(result["scripts"], 0)
        self.assertEqual(result["unsafeAttributes"], 0)
        self.assertFalse(result["unsafeRan"])
        self.assertIn("貼り付けたHTML", result["fileLabel"])
        self.assertTrue(result["overwriteDisabled"])

    def test_html_import_recovers_x_groups_and_youtube_settings(self):
        result = self.page.evaluate("""() => {
            window.twttr = {widgets: {load: () => {}}};
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('xpost') + insertedComponentHtml('video');
            const post = holder.children[0];
            post.dataset.xpostCount = '3';
            post.dataset.embedUrl = 'https://x.com/test/status/111';
            post.dataset.embedUrl2 = 'https://twitter.com/test/status/222';
            post.dataset.embedUrl3 = 'https://x.com/test/status/333';
            post.dataset.xpostCaption2 = 'second caption';
            const video = holder.children[1];
            video.dataset.embedUrl = 'https://youtu.be/abcdefghijk';
            video.dataset.videoBottomText = 'video caption';
            const html = formatOutputHtml(holder.innerHTML);
            importArticleHtml(html);
            const restoredPost = elements.preview.querySelector('[data-inserted-component="xpost"]');
            const restoredVideo = elements.preview.querySelector('[data-inserted-component="video"]');
            activeInsertedComponent = restoredPost;
            document.querySelector('.inserted-component-properties')._sync();
            const count = document.querySelector('#xpostCount');
            const restoredCount = count.value;
            count.value = '2';
            count.dispatchEvent(new Event('input', {bubbles:true}));
            count.dispatchEvent(new Event('change', {bubbles:true}));
            return {
              restoredCount,
              countAfterEdit: restoredPost.dataset.xpostCount,
              url2: restoredPost.dataset.embedUrl2,
              caption2: restoredPost.dataset.xpostCaption2,
              videoUrl: restoredVideo?.dataset.embedUrl,
              videoCaption: restoredVideo?.dataset.videoBottomText,
              iframe: restoredVideo?.querySelector('iframe')?.getAttribute('src'),
              exportedAgain: formatOutputHtml(getPersistablePreviewHtml())
            };
        }""")
        self.assertEqual(result['restoredCount'], '3')
        self.assertEqual(result['countAfterEdit'], '2')
        self.assertEqual(result['url2'], 'https://twitter.com/test/status/222')
        self.assertEqual(result['caption2'], 'second caption')
        self.assertEqual(result['videoUrl'], 'https://youtu.be/abcdefghijk')
        self.assertEqual(result['videoCaption'], 'video caption')
        self.assertEqual(result['iframe'], 'https://www.youtube.com/embed/abcdefghijk')
        self.assertIn('https://youtu.be/abcdefghijk', result['exportedAgain'])

    def test_html_import_recovers_x_side_text_and_trusted_video_iframe(self):
        result = self.page.evaluate("""() => {
            window.twttr = {widgets: {load: () => {}}};
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('xpost');
            const post = holder.firstElementChild;
            Object.assign(post.dataset, {
              embedUrl: 'https://x.com/test/status/111', xpostSideText: 'true',
              xpostSideContent: 'text', xpostTextSide: 'left', xpostMaxWidth: '40'
            });
            post.querySelector('[data-embed-text]').innerHTML = '<b>side text</b>';
            const html = formatOutputHtml(holder.innerHTML)
              + '<iframe src="https://www.youtube.com/embed/abcdefghijk" onload="window.unsafe = true"></iframe>'
              + '<iframe src="https://example.com/untrusted"></iframe>';
            importArticleHtml(html);
            const restored = elements.preview.querySelector('[data-inserted-component="xpost"]');
            return {
              count: restored.dataset.xpostCount,
              side: restored.dataset.xpostTextSide,
              enabled: restored.dataset.xpostSideText,
              width: restored.dataset.xpostMaxWidth,
              text: restored.querySelector('[data-embed-text]').textContent,
              iframes: [...elements.preview.querySelectorAll('iframe')].map(frame => frame.src),
              handlers: elements.preview.querySelectorAll('[onload]').length
            };
        }""")
        self.assertEqual(result['count'], '1')
        self.assertEqual(result['side'], 'left')
        self.assertEqual(result['enabled'], 'true')
        self.assertEqual(result['width'], '40')
        self.assertEqual(result['text'].strip(), 'side text')
        self.assertEqual(result['iframes'], ['https://www.youtube.com/embed/abcdefghijk'])
        self.assertEqual(result['handlers'], 0)

    def test_component_insert_save_restore(self):
        types = ["list", "note", "quote", "qa", "table", "image", "imageText", "imagePair",
                 "beforeAfter", "code", "rule", "xpost", "video", "linkCard", "toc"]
        result = self.page.evaluate("""types => {
            elements.preview.replaceChildren(); capturePreviewEdits();
            for (const type of types) {
                activeInsertedComponent = null; savedPreviewRange = null;
                window.getSelection().removeAllRanges();
                insertComponentAtSelection(type);
            }
            const payload = {settings: collectSettings(), previewHtml: getPersistablePreviewHtml()};
            restoreAutosavePayload(payload, 'round trip');
            return [...elements.preview.querySelectorAll('[data-inserted-component]')].map(el => el.dataset.insertedComponent);
        }""", types)
        self.assertCountEqual(result, types)

    def test_image_insert_ui_is_unified_and_legacy_types_remain_supported(self):
        result = self.page.evaluate("""() => {
            const insertTypes = [...document.querySelectorAll('#componentInsertSelect option')]
              .map(option => option.value).filter(Boolean);
            const quickTypes = [...document.querySelectorAll('.component-quick-button')]
              .map(button => button.dataset.componentType);
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('imagePair');
            const legacyPair = holder.firstElementChild;
            elements.preview.replaceChildren(legacyPair);
            activeInsertedComponent = legacyPair;
            document.querySelector('.inserted-component-properties')._sync();
            const pairLayoutClass = document.querySelector('.type-option-image').classList.contains('is-image-pair-layout');
            const legacyCount = document.querySelector('#componentImagePairCount').value;
            holder.innerHTML = insertedComponentHtml('image');
            const singleImage = holder.firstElementChild;
            elements.preview.replaceChildren(singleImage);
            activeInsertedComponent = singleImage;
            document.querySelector('.inserted-component-properties')._sync();
            return {
              insertTypes, quickTypes,
              legacyType: legacyPair.dataset.insertedComponent,
              legacyCount,
              pairLayoutClass,
              singleLayoutClass: document.querySelector('.type-option-image').classList.contains('is-image-pair-layout'),
              singleGroupTitle: document.querySelector('.component-image-primary-group .component-property-group-title').textContent,
              singleLinkLabel: document.querySelector('.component-image-primary-group label[for="imageLinkUrl"]').textContent,
              singleCaptionInGroup: Boolean(document.querySelector('.component-image-primary-group #componentImageCaption'))
            };
        }""")
        self.assertNotIn("imagePair", result["insertTypes"])
        self.assertNotIn("imagePair", result["quickTypes"])
        self.assertIn("image", result["insertTypes"])
        self.assertIn("image", result["quickTypes"])
        self.assertEqual(result["legacyType"], "imagePair")
        self.assertEqual(result["legacyCount"], "2")
        self.assertTrue(result["pairLayoutClass"])
        self.assertTrue(result["singleLayoutClass"])
        self.assertEqual(result["singleGroupTitle"], "1枚目")
        self.assertEqual(result["singleLinkLabel"], "1枚目のリンクURL")
        self.assertTrue(result["singleCaptionInGroup"])

    def test_note_spot_presets_use_content_width_and_keep_legacy_notes_full_width(self):
        result = self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('note');
            const note = holder.firstElementChild;
            elements.preview.replaceChildren(note);
            activeInsertedComponent = note;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const legacyLayout = document.querySelector('#noteWidthMode').value;
            const preset = document.querySelector('#notePreset');
            const applyPreset = value => {
              preset.value = value;
              preset.dispatchEvent(new Event('change', {bubbles: true}));
              return {
                preset: note.dataset.notePreset,
                layout: note.dataset.noteLayout,
                display: note.style.display,
                width: note.style.width,
                icon: note.querySelector('[data-note-icon]')?.textContent,
                borderStyle: note.style.borderStyle
              };
            };
            const spotMemo = applyPreset('spotMemo');
            const spotWarning = applyPreset('spotWarning');
            return {
              legacyLayout,
              optionValues: [...preset.options].map(option => option.value),
              spotMemo,
              spotWarning,
              savedHtml: getPersistablePreviewHtml()
            };
        }""")
        self.assertEqual(result["legacyLayout"], "block")
        self.assertIn("spotMemo", result["optionValues"])
        self.assertIn("spotWarning", result["optionValues"])
        self.assertEqual(result["spotMemo"]["layout"], "spot")
        self.assertEqual(result["spotMemo"]["display"], "inline-block")
        self.assertEqual(result["spotMemo"]["width"], "fit-content")
        self.assertEqual(result["spotMemo"]["icon"], "📌")
        self.assertEqual(result["spotWarning"]["layout"], "spot")
        self.assertEqual(result["spotWarning"]["icon"], "⚠️")
        self.assertIn('data-note-layout="spot"', result["savedHtml"])

    def test_empty_text_component_keeps_layout_and_accepts_text_again(self):
        self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('note');
            const note = elements.preview.firstElementChild;
            activeInsertedComponent = note;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const layout = document.querySelector('#noteWidthMode');
            layout.value = 'spot';
            layout.dispatchEvent(new Event('change', {bubbles:true}));
        }""")
        note = self.page.locator('[data-inserted-component="note"]')
        note.click()
        self.page.keyboard.press('Control+A')
        selected = self.page.evaluate("""() => {
            const range = window.getSelection().getRangeAt(0);
            const note = elements.preview.querySelector('[data-inserted-component="note"]');
            return {inside:note.contains(range.commonAncestorContainer), text:range.toString()};
        }""")
        self.assertTrue(selected['inside'])
        self.assertEqual(selected['text'], 'メモや注意事項を入力')
        self.page.keyboard.press('Backspace')
        empty = self.page.evaluate("""() => {
            const note = elements.preview.querySelector('[data-inserted-component="note"]');
            const rect = note?.getBoundingClientRect();
            return {exists:!!note, layout:note?.dataset.noteLayout, display:note?.style.display,
              placeholder:!!note?.querySelector(':scope > br[data-empty-editable-placeholder]'),
              width:rect?.width || 0, height:rect?.height || 0,
              outputHasMarker:formatOutputHtml(getPersistablePreviewHtml()).includes('data-empty-editable-placeholder')};
        }""")
        self.assertTrue(empty['exists'])
        self.assertEqual(empty['layout'], 'spot')
        self.assertEqual(empty['display'], 'inline-block')
        self.assertTrue(empty['placeholder'])
        self.assertGreaterEqual(empty['width'], 128)
        self.assertGreater(empty['height'], 0)
        self.assertFalse(empty['outputHasMarker'])

        self.page.keyboard.type('再入力')
        restored = self.page.evaluate("""() => {
            const note = elements.preview.querySelector('[data-inserted-component="note"]');
            return {text:note.textContent, layout:note.dataset.noteLayout,
              placeholder:!!note.querySelector('[data-empty-editable-placeholder]')};
        }""")
        self.assertEqual(restored['text'], '再入力')
        self.assertEqual(restored['layout'], 'spot')
        self.assertFalse(restored['placeholder'])

    def test_image_count_conversion_preserves_legacy_pair_content(self):
        result = self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('imagePair');
            const pair = holder.firstElementChild;
            const images = pair.querySelectorAll('img[data-inserted-image]');
            images[0].src = 'https://example.com/one.png';
            images[1].src = 'https://example.com/two.png';
            const secondLink = document.createElement('a');
            secondLink.href = 'https://example.com/two';
            images[1].before(secondLink);
            secondLink.appendChild(images[1]);
            const secondCaption = document.createElement('div');
            secondCaption.dataset.imageCaption = 'true';
            secondCaption.contentEditable = 'true';
            secondCaption.textContent = 'second caption';
            pair.children[1].appendChild(secondCaption);
            elements.preview.replaceChildren(pair);
            activeInsertedComponent = pair;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const count = document.querySelector('#componentImagePairCount');
            count.value = '1';
            count.dispatchEvent(new Event('change', {bubbles: true}));
            const singleType = activeInsertedComponent.dataset.insertedComponent;
            count.value = '3';
            count.dispatchEvent(new Event('change', {bubbles: true}));
            const restored = activeInsertedComponent;
            const restoredImages = restored.querySelectorAll('img[data-inserted-image]');
            const restoredState = {
              singleType,
              restoredType: restored.dataset.insertedComponent,
              count: restoredImages.length,
              firstSrc: restoredImages[0].getAttribute('src'),
              secondSrc: restoredImages[1].getAttribute('src'),
              secondLink: restoredImages[1].parentElement.getAttribute('href'),
              secondCaption: restored.children[1].querySelector('[data-image-caption]')?.textContent
            };
            count.value = '2';
            count.dispatchEvent(new Event('change', {bubbles: true}));
            restoredState.reducedCount = activeInsertedComponent.querySelectorAll('img[data-inserted-image]').length;
            count.value = '3';
            count.dispatchEvent(new Event('change', {bubbles: true}));
            restoredState.expandedCount = activeInsertedComponent.querySelectorAll('img[data-inserted-image]').length;
            return restoredState;
        }""")
        self.assertEqual(result["singleType"], "image")
        self.assertEqual(result["restoredType"], "imagePair")
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["firstSrc"], "https://example.com/one.png")
        self.assertEqual(result["secondSrc"], "https://example.com/two.png")
        self.assertEqual(result["secondLink"], "https://example.com/two")
        self.assertEqual(result["secondCaption"], "second caption")
        self.assertEqual(result["reducedCount"], 2)
        self.assertEqual(result["expandedCount"], 3)

    def test_deleting_text_across_table_cells_preserves_table_structure(self):
        self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedTableHtml();
            const table = holder.firstElementChild;
            elements.preview.replaceChildren(table);
            const cells = Array.from(table.rows[0].cells);
            cells[0].textContent = 'alpha';
            cells[1].textContent = 'beta';
            cells[2].textContent = 'gamma';
            const range = document.createRange();
            range.setStart(cells[0].firstChild, 2);
            range.setEnd(cells[2].firstChild, 2);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            cells[0].focus();
            selection.removeAllRanges();
            selection.addRange(range);
        }""")
        self.page.keyboard.press("Backspace")
        result = self.page.evaluate("""() => {
            const table = elements.preview.querySelector('table');
            return {
              rowCount: table.rows.length,
              columnCounts: Array.from(table.rows).map(row => row.cells.length),
              firstRowTexts: Array.from(table.rows[0].cells).map(cell => cell.textContent),
              firstRowTags: Array.from(table.rows[0].cells).map(cell => cell.tagName),
              caretCellIndex: Array.from(table.rows[0].cells).indexOf(
                window.getSelection().focusNode?.parentElement?.closest('th, td')
              )
            };
        }""")
        self.assertEqual(result["rowCount"], 3)
        self.assertEqual(result["columnCounts"], [3, 3, 3])
        self.assertEqual(result["firstRowTexts"], ["al", "", "mma"])
        self.assertEqual(result["firstRowTags"], ["TH", "TH", "TH"])
        self.assertEqual(result["caretCellIndex"], 0)

    def test_table_row_and_column_delete_use_caret_or_selected_cells(self):
        result = self.page.evaluate("""() => {
            const makeTable = () => {
              const holder = document.createElement('div');
              holder.innerHTML = insertedTableHtml();
              const table = holder.firstElementChild;
              Array.from(table.rows).forEach((row, rowIndex) => {
                Array.from(row.cells).forEach((cell, columnIndex) => {
                  cell.textContent = `${rowIndex}-${columnIndex}`;
                });
              });
              elements.preview.replaceChildren(table);
              activePreviewTable = table;
              activeInsertedComponent = table;
              selectedTableCells = [];
              return table;
            };
            const setCaret = (cell) => {
              const range = document.createRange();
              range.selectNodeContents(cell);
              range.collapse(true);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
            };

            let table = makeTable();
            setCaret(table.rows[1].cells[1]);
            document.querySelector('#tableDeleteRowButton').click();
            const caretRows = Array.from(table.rows, row => row.cells[0].textContent);

            table = makeTable();
            setCaret(table.rows[1].cells[1]);
            document.querySelector('#tableDeleteColumnButton').click();
            const caretColumns = Array.from(table.rows[0].cells, cell => cell.textContent);

            table = makeTable();
            savedPreviewRange = null;
            selectedTableCells = [table.rows[0].cells[0], table.rows[2].cells[1]];
            selectedTableCells.forEach(cell => cell.classList.add('table-cell-selected'));
            document.querySelector('#tableDeleteRowButton').click();
            const selectedRows = Array.from(table.rows, row => row.cells[0].textContent);

            table = makeTable();
            savedPreviewRange = null;
            selectedTableCells = [table.rows[0].cells[0], table.rows[2].cells[2]];
            selectedTableCells.forEach(cell => cell.classList.add('table-cell-selected'));
            document.querySelector('#tableDeleteColumnButton').click();
            const selectedColumns = Array.from(table.rows[0].cells, cell => cell.textContent);
            return {caretRows, caretColumns, selectedRows, selectedColumns};
        }""")
        self.assertEqual(result["caretRows"], ["0-0", "2-0"])
        self.assertEqual(result["caretColumns"], ["0-0", "0-2"])
        self.assertEqual(result["selectedRows"], ["1-0"])
        self.assertEqual(result["selectedColumns"], ["0-1"])

    def test_toc_flag_adds_back_links_to_headings(self):
        result = self.page.evaluate("""() => {
            const makeHeading = (text) => {
              const fragment = document.createDocumentFragment();
              fragment.appendChild(document.createTextNode(text));
              return createDocumentBlockFromFragment('heading', fragment, readDocumentBlockSettings('heading'));
            };
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('toc');
            const toc = holder.firstElementChild;
            elements.preview.replaceChildren(toc, makeHeading('見出しA'), makeHeading('見出しB'));
            refreshTocComponent(toc);
            activeInsertedComponent = toc;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const flag = document.querySelector('#tocBackLinks');
            flag.checked = true;
            flag.dispatchEvent(new Event('change', {bubbles: true}));
            const links = Array.from(elements.preview.querySelectorAll('[data-toc-back-link]'));
            const enabled = {
              flag: toc.dataset.tocBackLinks,
              tocId: toc.id,
              count: links.length,
              hrefs: links.map(link => link.getAttribute('href')),
              labels: links.map(link => link.textContent),
              headingDisplay: elements.preview.querySelector('[data-inserted-component="heading"] h2').style.display
            };
            const outputHolder = document.createElement('div');
            outputHolder.innerHTML = formatOutputHtml(getPersistablePreviewHtml());
            enabled.outputLinks = Array.from(outputHolder.querySelectorAll(`a[href="#${toc.id}"]`)).length;
            enabled.outputEditorMarkers = outputHolder.querySelectorAll('[data-toc-back-link]').length;

            flag.checked = false;
            flag.dispatchEvent(new Event('change', {bubbles: true}));
            const disabledCount = elements.preview.querySelectorAll('[data-toc-back-link]').length;
            const disabledDisplay = elements.preview.querySelector('[data-inserted-component="heading"] h2').style.display;

            flag.checked = true;
            flag.dispatchEvent(new Event('change', {bubbles: true}));
            toc.remove();
            capturePreviewEdits();
            const afterTocRemoval = elements.preview.querySelectorAll('[data-toc-back-link]').length;
            return {enabled, disabledCount, disabledDisplay, afterTocRemoval};
        }""")
        self.assertEqual(result["enabled"]["flag"], "true")
        self.assertTrue(result["enabled"]["tocId"].startswith("p-player-toc"))
        self.assertEqual(result["enabled"]["count"], 2)
        self.assertEqual(result["enabled"]["hrefs"], [f'#{result["enabled"]["tocId"]}'] * 2)
        self.assertEqual(result["enabled"]["labels"], ["↑ 目次", "↑ 目次"])
        self.assertEqual(result["enabled"]["headingDisplay"], "flex")
        self.assertEqual(result["enabled"]["outputLinks"], 2)
        self.assertEqual(result["enabled"]["outputEditorMarkers"], 0)
        self.assertEqual(result["disabledCount"], 0)
        self.assertEqual(result["disabledDisplay"], "")
        self.assertEqual(result["afterTocRemoval"], 0)

    def test_toc_back_links_only_on_listed_headings(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('toc') +
              ['Alpha', 'Beta', 'Gamma'].map((text, i) =>
                `<div data-inserted-component="heading"><h2 id="heading-${i+1}"><span data-heading-content>${text}</span></h2></div>`).join('');
            const toc = elements.preview.querySelector('[data-inserted-component="toc"]');
            refreshTocComponent(toc);
            toc.querySelector('a[href="#heading-2"]').closest('li').remove();
            activeInsertedComponent = toc;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const flag = document.querySelector('#tocBackLinks');
            flag.checked = true;
            flag.dispatchEvent(new Event('change', {bubbles:true}));
            const links = () => [...elements.preview.querySelectorAll('h2')].map(
              heading => heading.querySelector('[data-toc-back-link]')?.textContent || '');
            const initial = links();
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            return {initial, restored:links()};
        }""")
        self.assertEqual(result['initial'], ['↑ 目次', '', '↑ 目次'])
        self.assertEqual(result['restored'], ['↑ 目次', '', '↑ 目次'])

    def test_toc_fit_content_and_custom_colors(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('toc') +
              '<div data-inserted-component="heading"><h2 id="heading-1"><span data-heading-content>短い見出し</span></h2></div>';
            const toc = elements.preview.querySelector('[data-inserted-component="toc"]');
            refreshTocComponent(toc);
            activeInsertedComponent = toc;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const set = (id, value) => {
              const control = document.querySelector(id);
              if (control.type === 'checkbox') control.checked = value;
              else control.value = value;
              control.dispatchEvent(new Event('input', {bubbles:true}));
            };
            set('#tocFitContent', true);
            set('#tocBackgroundColorText', '#112233');
            set('#tocBorderColorText', '#445566');
            set('#tocTitleColorText', '#778899');
            set('#tocTextColorText', '#aabbcc');
            set('#tocAccentColorText', '#cc3300');
            const title = toc.querySelector('[data-toc-title]');
            const list = toc.querySelector('[data-toc-list]');
            const button = toc.querySelector('[data-toc-refresh]');
            const custom = {
              fit: toc.dataset.tocFitContent,
              display: toc.style.display,
              narrower: toc.getBoundingClientRect().width < elements.preview.getBoundingClientRect().width,
              background: toc.style.backgroundColor,
              border: toc.style.borderColor,
              title: title.style.color,
              text: list.style.color,
              accent: button.style.color
            };
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const restoredToc = elements.preview.querySelector('[data-inserted-component="toc"]');
            const restored = {
              fit: restoredToc.dataset.tocFitContent,
              display: restoredToc.style.display,
              background: restoredToc.dataset.tocBackground,
              title: restoredToc.dataset.tocTitleColor
            };
            activeInsertedComponent = restoredToc;
            properties._sync();
            document.querySelector('#tocPreset').value = 'accent';
            document.querySelector('#tocPreset').dispatchEvent(new Event('change', {bubbles:true}));
            return {custom, restored, presetReset: {
              hasCustom: restoredToc.hasAttribute('data-toc-background'),
              background: restoredToc.style.backgroundColor,
              control: document.querySelector('#tocBackgroundColorText').value
            }};
        }""")
        self.assertEqual(result['custom']['fit'], 'true')
        self.assertEqual(result['custom']['display'], 'inline-block')
        self.assertTrue(result['custom']['narrower'])
        self.assertEqual(result['custom']['background'], 'rgb(17, 34, 51)')
        self.assertEqual(result['custom']['border'], 'rgb(68, 85, 102)')
        self.assertEqual(result['custom']['title'], 'rgb(119, 136, 153)')
        self.assertEqual(result['custom']['text'], 'rgb(170, 187, 204)')
        self.assertEqual(result['custom']['accent'], 'rgb(204, 51, 0)')
        self.assertEqual(result['restored'], {
            'fit': 'true', 'display': 'inline-block',
            'background': '#112233', 'title': '#778899'})
        self.assertFalse(result['presetReset']['hasCustom'])
        self.assertEqual(result['presetReset']['background'], 'rgb(239, 246, 255)')
        self.assertEqual(result['presetReset']['control'], '#eff6ff')

    def test_toc_heading_numbers_toggle_reorder_and_html_round_trip(self):
        result = self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('toc');
            const toc = holder.firstElementChild;
            const headings = ['Alpha', 'Beta'].map(text => {
              const fragment = document.createDocumentFragment();
              fragment.append(text);
              return createDocumentBlockFromFragment('heading', fragment, readDocumentBlockSettings('heading'));
            });
            elements.preview.replaceChildren(toc, ...headings);
            refreshTocComponent(toc);
            activeInsertedComponent = toc;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const flag = document.querySelector('#tocHeadingNumbers');
            const initial = flag.checked;
            flag.checked = true;
            flag.dispatchEvent(new Event('change', {bubbles:true}));
            const numbers = () => [...elements.preview.querySelectorAll('[data-toc-heading-number]')].map(el => el.textContent);
            const enabled = numbers();
            elements.preview.insertBefore(headings[1], headings[0]);
            capturePreviewEdits();
            const reorderedFirst = elements.preview.querySelector('[data-inserted-component="heading"]').textContent;
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const restored = numbers();
            const restoredToc = elements.preview.querySelector('[data-inserted-component="toc"]');
            activeInsertedComponent = restoredToc;
            properties._sync();
            flag.checked = false;
            flag.dispatchEvent(new Event('change', {bubbles:true}));
            return {initial, enabled, reorderedFirst, restored, disabled: numbers(),
              titles: [...elements.preview.querySelectorAll('[data-heading-content]')].map(el => el.textContent.trim())};
        }""")
        self.assertFalse(result['initial'])
        self.assertEqual(result['enabled'], ['1. ', '2. '])
        self.assertIn('1. Beta', result['reorderedFirst'])
        self.assertEqual(result['restored'], ['1. ', '2. '])
        self.assertEqual(result['disabled'], [])
        self.assertEqual(result['titles'], ['Beta', 'Alpha'])

    def test_toc_heading_number_color_matches_first_text(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('toc') + `
              <div data-inserted-component="heading"><h2 style="color:#123456">
                <span data-heading-content>通常の見出し</span></h2></div>
              <div data-inserted-component="heading"><h2 style="color:#123456">
                <span data-heading-content> <span></span><span style="color:#ff0000"><b>赤</b></span><span style="color:#0000ff">青</span></span></h2></div>`;
            const toc = elements.preview.querySelector('[data-inserted-component="toc"]');
            toc.dataset.tocHeadingNumbers = 'true';
            refreshTocComponent(toc);
            syncTocBackLinks();
            const colors = root => [...root.querySelectorAll('[data-toc-heading-number]')].map(el => el.style.color);
            const initial = colors(elements.preview);
            elements.preview.querySelector('[data-heading-content] span[style]').style.color = '#008000';
            capturePreviewEdits();
            const changed = colors(elements.preview);
            const html = formatOutputHtml(getPersistablePreviewHtml());
            const output = document.createElement('div');
            output.innerHTML = html;
            const exported = colors(output);
            importArticleHtml(html);
            return {initial, changed, exported, restored: colors(elements.preview)};
        }""")
        self.assertEqual(result['initial'], ['rgb(18, 52, 86)', 'rgb(255, 0, 0)'])
        for stage in ('changed', 'exported', 'restored'):
            self.assertEqual(result[stage], ['rgb(18, 52, 86)', 'rgb(0, 128, 0)'])

    def test_toc_numbering_skips_headings_missing_from_toc(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('toc') +
              ['Alpha', 'Beta', 'Gamma', 'Delta'].map((text, i) =>
                `<div data-inserted-component="heading"><h2 id="heading-${i+1}"><span data-heading-content>${text}</span></h2></div>`).join('');
            const toc = elements.preview.querySelector('[data-inserted-component="toc"]');
            toc.dataset.tocHeadingNumbers = 'true';
            refreshTocComponent(toc);
            const numbers = () => [...elements.preview.querySelectorAll('h2')].map(
              heading => heading.querySelector('[data-toc-heading-number]')?.textContent || '');
            const initial = numbers();
            toc.querySelector('a[href="#heading-1"]').closest('li').remove();
            toc.querySelector('a[href="#heading-3"]').closest('li').remove();
            capturePreviewEdits();
            const filtered = numbers();
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const restored = numbers();
            elements.preview.querySelector('[data-toc-list]').replaceChildren();
            capturePreviewEdits();
            return {initial, filtered, restored, empty: numbers()};
        }""")
        self.assertEqual(result['initial'], ['1. ', '2. ', '3. ', '4. '])
        self.assertEqual(result['filtered'], ['', '1. ', '', '2. '])
        self.assertEqual(result['restored'], ['', '1. ', '', '2. '])
        self.assertEqual(result['empty'], ['', '', '', ''])

    def test_toc_line_height_is_roomier_and_adjustable(self):
        result = self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('toc');
            const toc = holder.firstElementChild;
            const list = toc.querySelector('[data-toc-list]');
            elements.preview.replaceChildren(toc);
            activeInsertedComponent = toc;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const control = document.querySelector('#tocLineHeight');
            const initial = {
              control: control.value,
              dataset: toc.dataset.tocLineHeight,
              style: list.style.lineHeight
            };
            control.value = '2.4';
            control.dispatchEvent(new Event('change', {bubbles: true}));
            const adjusted = {
              dataset: toc.dataset.tocLineHeight,
              style: list.style.lineHeight,
              savedHtml: getPersistablePreviewHtml()
            };

            holder.innerHTML = insertedComponentHtml('toc');
            const legacyToc = holder.firstElementChild;
            const legacyList = legacyToc.querySelector('[data-toc-list]');
            legacyToc.removeAttribute('data-toc-line-height');
            legacyList.style.lineHeight = '1.9';
            normalizeTocDesign(legacyToc);
            return {
              initial,
              adjusted,
              legacyDataset: legacyToc.dataset.tocLineHeight,
              legacyStyle: legacyList.style.lineHeight
            };
        }""")
        self.assertEqual(result["initial"], {"control": "2.1", "dataset": "2.1", "style": "2.1"})
        self.assertEqual(result["adjusted"]["dataset"], "2.4")
        self.assertEqual(result["adjusted"]["style"], "2.4")
        self.assertIn('data-toc-line-height="2.4"', result["adjusted"]["savedHtml"])
        self.assertEqual(result["legacyDataset"], "1.9")
        self.assertEqual(result["legacyStyle"], "1.9")

    def test_toc_spacing_changes_visible_rows_with_imported_text_styles(self):
        result = self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('toc');
            const toc = holder.firstElementChild;
            const list = toc.querySelector('[data-toc-list]');
            list.innerHTML = '<li style="line-height:20px"><a href="#one"><span style="line-height:20px">First</span></a></li><li style="line-height:20px"><a href="#two">Second</a></li>';
            elements.preview.replaceChildren(toc);
            activeInsertedComponent = toc;
            document.querySelector('.inserted-component-properties')._sync();
            const input = document.querySelector('#tocLineHeight');
            const measure = value => {
              input.value = value;
              input.dispatchEvent(new Event('input', {bubbles:true}));
              const items = list.querySelectorAll('li');
              return items[1].getBoundingClientRect().top - items[0].getBoundingClientRect().top;
            };
            const small = measure('1.2');
            const large = measure('3');
            return {small, large};
        }""")
        self.assertGreater(result['large'], result['small'] + 15)

    def test_obfuscated_script_url_is_removed(self):
        result = self.page.evaluate("""() => {
            return sanitizeMarkdownHtml('<a href="java&#10;script:alert(1)">link</a>');
        }""")
        self.assertEqual(result, "link")

    def test_copy_boundary_comments_are_stamped_safely(self):
        result = self.page.evaluate("""() => {
            const stamped = stampBoundaryCommentsForCopy(
              '<!-- ーーーーーーー p-player 開始：コピー時に日時を記録 ーーーーーーー -->\\n'
              + '<p>本文</p>\\n'
              + '<!-- ーーーーーーー p-player 終了:copy time ーーーーーーー -->\\n'
              + '<!-- keep this comment -->'
            );
            elements.htmlOutputMode.value = 'noComments';
            elements.includeBoundaryComments.checked = true;
            const noCommentsMode = formatOutputHtml('<p>本文</p><!-- remove this comment -->');
            const missingBoundaries = stampBoundaryCommentsForCopy('<p>本文</p>');
            elements.includeBoundaryComments.checked = false;
            const disabled = formatOutputHtml(
              '<!-- ーーーーーーー p-player 開始：old ーーーーーーー --><p>本文</p>'
              + '<!-- ーーーーーーー p-player 終了：old ーーーーーーー -->'
            );
            return {stamped, noCommentsMode, missingBoundaries, disabled};
        }""")
        self.assertIn("p-player 開始：コピー日時", result["stamped"])
        self.assertIn("p-player 終了：コピー日時", result["stamped"])
        self.assertIn("<!-- keep this comment -->", result["stamped"])
        self.assertIn("p-player 開始：コピー時に日時を記録", result["noCommentsMode"])
        self.assertIn("p-player 終了：コピー時に日時を記録", result["noCommentsMode"])
        self.assertNotIn("remove this comment", result["noCommentsMode"])
        self.assertIn("p-player 開始：コピー日時", result["missingBoundaries"])
        self.assertIn("p-player 終了：コピー日時", result["missingBoundaries"])
        self.assertNotIn("p-player", result["disabled"])

    def test_markdown_and_csv(self):
        result = self.page.evaluate("""() => {
            importMarkdownText('# Heading\\n\\nBody **bold**\\n\\n- one\\n- two\\n\\n| a | b |\\n| - | - |\\n| 1 | 2 |\\n\\n```js\\nconst x = 1;\\n```', 'test', {clearPreview:true});
            return {types: [...elements.preview.querySelectorAll('[data-inserted-component]')].map(el => el.dataset.insertedComponent),
              csv: parseCsv('a,b\\r\\n"one,two","line1\\nline2"\\r\\n')};
        }""")
        for component in ["heading", "body", "list", "table", "code"]:
            self.assertIn(component, result["types"])
        self.assertEqual(result["csv"], [["a", "b"], ["one,two", "line1\nline2"]])

    def test_startup_with_storage_disabled(self):
        self.page.add_init_script("Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('Blocked', 'SecurityError'); } });")
        self.page.reload()
        self.assertEqual(self.page.locator('#componentToolsSection').count(), 1)


if __name__ == "__main__":
    unittest.main()
