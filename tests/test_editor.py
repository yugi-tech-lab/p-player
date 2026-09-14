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

    def test_obfuscated_script_url_is_removed(self):
        result = self.page.evaluate("""() => {
            return sanitizeMarkdownHtml('<a href="java&#10;script:alert(1)">link</a>');
        }""")
        self.assertEqual(result, "link")

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
