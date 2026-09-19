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
            self.page.evaluate("document.querySelector('#activeArticleFilePath').nextElementSibling.id"),
            "characterCount",
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
