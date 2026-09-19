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

    def test_obfuscated_script_url_is_removed(self):
        result = self.page.evaluate("""() => {
            return sanitizeMarkdownHtml('<a href="java&#10;script:alert(1)">link</a>');
        }""")
        self.assertEqual(result, "link")

    def test_copy_boundary_comments_are_stamped_safely(self):
        result = self.page.evaluate("""() => ({
            stamped: stampBoundaryCommentsForCopy(
              '<!-- ーーーーーーー p-player 開始：コピー時に日時を記録 ーーーーーーー -->\\n'
              + '<p>本文</p>\\n'
              + '<!-- ーーーーーーー p-player 終了:copy time ーーーーーーー -->\\n'
              + '<!-- keep this comment -->'
            ),
            nullInput: stampBoundaryCommentsForCopy(null)
        })""")
        self.assertIn("p-player 開始：コピー日時", result["stamped"])
        self.assertIn("p-player 終了：コピー日時", result["stamped"])
        self.assertIn("<!-- keep this comment -->", result["stamped"])
        self.assertEqual(result["nullInput"], "")

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
