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

    def test_simple_japanese_article_themes_apply_and_persist(self):
        result = self.page.evaluate("""() => {
            const expected = {
              waSumi:{label:'和・墨と朱',pattern:'minimal',card:'plain',main:'#34312f',sub:'#a63d32',body:'#34312f'},
              waKinari:{label:'和・生成り',pattern:'paper',card:'paper',main:'#9a7644',sub:'#5c5142',body:'#3f3a2f'},
              waIndigo:{label:'和・藍',pattern:'leftLine',card:'simple',main:'#31556d',sub:'#f3f0e6',body:'#343a40'}
            };
            const select = document.querySelector('#preset');
            const applied = Object.entries(expected).map(([name, spec]) => {
              select.value = name;
              select.dispatchEvent(new Event('change', {bubbles:true}));
              const heading = elements.preview.querySelector('[data-inserted-component="heading"]');
              const body = elements.preview.querySelector('[data-inserted-component="body"]');
              const headingSettings = parseDocumentBlockSettings(heading);
              const bodySettings = parseDocumentBlockSettings(body);
              return {name, label:select.selectedOptions[0].textContent,
                pattern:headingSettings.pattern, card:bodySettings.cardPattern,
                main:headingSettings.mainColorText, sub:headingSettings.subColorText,
                body:bodySettings.bodyColorText, headingText:heading.textContent,
                bodyText:body.textContent};
            });
            document.querySelector('#presetGalleryTrigger').click();
            const galleryLabels = [...document.querySelectorAll('#presetGalleryGrid .preset-gallery-card-label')]
              .map(label => label.textContent).filter(label => label.startsWith('和・'));
            document.querySelector('#presetGalleryDialog').close();
            select.value = 'waKinari';
            select.dispatchEvent(new Event('change', {bubbles:true}));
            const settings = collectSettings();
            const html = getPersistablePreviewHtml();
            applySettings(settings, {renderPreview:false});
            formattedPreviewHtml = html;
            render({forceReset:true});
            return {expected, applied, galleryLabels, restored:elements.preset.value,
              restoredPattern:parseDocumentBlockSettings(elements.preview.querySelector('[data-inserted-component="heading"]')).pattern};
        }""")
        for state in result['applied']:
            spec = result['expected'][state['name']]
            for key in ('label', 'pattern', 'card', 'main', 'sub', 'body'):
                self.assertEqual(state[key], spec[key], f"{state['name']} {key}")
            self.assertTrue(state['headingText'].strip())
            self.assertTrue(state['bodyText'].strip())
        self.assertEqual(result['galleryLabels'], ['和・墨と朱', '和・生成り', '和・藍'])
        self.assertEqual(result['restored'], 'waKinari')
        self.assertEqual(result['restoredPattern'], 'paper')

    def test_add_document_blocks_after_selected_plain_or_card_body(self):
        result = self.page.evaluate("""() => {
            const actions = [
              ['addHeadingBlockButton', 'heading'],
              ['addBodyBlockButton', 'plain'],
              ['addBodyCardBlockButton', 'card']
            ];
            const states = [];
            for (const selectedCard of [false, true]) {
              for (const [buttonId, addedMode] of actions) {
                const selected = document.createElement('div');
                selected.dataset.insertedComponent = 'body';
                selected.textContent = selectedCard ? '選択中の本文カード' : '選択中の通常本文';
                applyDocumentBlockAppearance(selected, {...readDocumentBlockSettings('body'), includeCard:selectedCard});
                const following = document.createElement('div');
                following.dataset.insertedComponent = 'body';
                following.textContent = '後ろの本文';
                applyDocumentBlockAppearance(following, {...readDocumentBlockSettings('body'), includeCard:false});
                elements.preview.replaceChildren(selected, following);
                activeInsertedComponent = selected;
                setDocumentBlockControls(selected);
                const range = document.createRange();
                range.selectNodeContents(selected);
                range.collapse(false);
                savedPreviewRange = range.cloneRange();
                const selection = getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                updateInsertionAvailability();
                const availability = Object.fromEntries(
                  actions.map(([id, mode]) => [mode, document.getElementById(id).getAttribute('aria-disabled')])
                );
                document.getElementById(buttonId).click();
                const children = [...elements.preview.children];
                const inserted = children[1];
                states.push({selectedCard, addedMode, availability,
                  order:children.map(child => child.dataset.insertedComponent),
                  selectedText:children[0].textContent.trim(),
                  followingText:children[2].textContent.trim(),
                  outside:inserted.parentElement === elements.preview && !selected.contains(inserted),
                  insertedCard:inserted.dataset.insertedComponent === 'body' ? isBodyCard(inserted) : null,
                  invalid:findInvalidNestedStructure()?.message || null,
                  active:activeInsertedComponent === inserted,
                  editable:inserted.dataset.insertedComponent === 'heading'
                    ? inserted.querySelector('[data-heading-content]')?.contentEditable
                    : inserted.contentEditable});
              }
            }
            return states;
        }""")
        self.assertEqual(len(result), 6)
        for state in result:
            self.assertEqual(state['availability'], dict(heading='false', plain='false', card='false'))
            expected_type = 'heading' if state['addedMode'] == 'heading' else 'body'
            self.assertEqual(state['order'], ['body', expected_type, 'body'])
            self.assertEqual(state['selectedText'],
                             '選択中の本文カード' if state['selectedCard'] else '選択中の通常本文')
            self.assertEqual(state['followingText'], '後ろの本文')
            self.assertTrue(state['outside'])
            expected_card = None if state['addedMode'] == 'heading' else state['addedMode'] == 'card'
            self.assertEqual(state['insertedCard'], expected_card)
            self.assertIsNone(state['invalid'])
            self.assertTrue(state['active'])
            self.assertEqual(state['editable'], 'true')

    def test_active_plain_body_selection_outline_is_drawn_outside_content(self):
        result = self.page.evaluate("""() => {
            const plain = document.createElement('div');
            plain.dataset.insertedComponent = 'body';
            plain.textContent = '通常本文';
            applyDocumentBlockAppearance(plain, {...readDocumentBlockSettings('body'), includeCard:false, cardPadding:'0'});
            elements.preview.replaceChildren(plain);
            activeInsertedComponent = plain;
            setDocumentBlockControls(plain);
            const activePadding = getComputedStyle(plain).paddingLeft;
            const outlineOffset = getComputedStyle(plain).outlineOffset;
            const previewPaddingLeft = getComputedStyle(elements.preview).paddingLeft;
            const previewPaddingRight = getComputedStyle(elements.preview).paddingRight;
            const saved = document.createElement('div');
            saved.innerHTML = getPersistablePreviewHtml();
            const restoredPlain = saved.querySelector('[data-inserted-component="body"]');
            return {
              activePadding,
              outlineOffset,
              previewPaddingLeft,
              previewPaddingRight,
              savedClass:restoredPlain.className,
              savedInlinePadding:restoredPlain.style.paddingLeft
            };
        }""")
        self.assertEqual(result['activePadding'], '0px')
        self.assertEqual(result['outlineOffset'], '6px')
        self.assertEqual(result['previewPaddingLeft'], '2px')
        self.assertEqual(result['previewPaddingRight'], '2px')
        self.assertEqual(result['savedClass'], '')
        self.assertEqual(result['savedInlinePadding'], '')

    def test_double_line_heading_uses_two_thin_lines_in_same_color(self):
        result = self.page.evaluate("""() => {
            const heading = document.createElement('div');
            heading.style.cssText = getHeadingStyle('doubleLine', '#123456', '#abcdef', 8, '#172033');
            document.body.append(heading);
            const style = getComputedStyle(heading);
            const state = {
              topWidth:style.borderTopWidth,
              bottomWidth:style.borderBottomWidth,
              topColor:style.borderTopColor,
              bottomColor:style.borderBottomColor
            };
            heading.remove();
            return state;
        }""")
        self.assertEqual(result['topWidth'], '2px')
        self.assertEqual(result['bottomWidth'], '2px')
        self.assertEqual(result['topColor'], 'rgb(18, 52, 86)')
        self.assertEqual(result['bottomColor'], result['topColor'])

    def test_text_link_can_open_in_new_tab_from_toolbar_checkbox(self):
        result = self.page.evaluate("""() => {
            const body = document.createElement('div');
            body.dataset.insertedComponent = 'body';
            body.textContent = 'リンク文字';
            applyDocumentBlockAppearance(body, {...readDocumentBlockSettings('body'), includeCard:false});
            elements.preview.replaceChildren(body);
            const selectBodyText = () => {
              const text = body.firstChild;
              const range = document.createRange();
              range.selectNodeContents(text);
              const selection = getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
            };
            const url = document.querySelector('#selectionLinkUrl');
            const checkbox = document.querySelector('#selectionLinkNewTab');
            const label = checkbox.closest('label');
            const unlink = document.querySelector('#selectionUnlinkButton');
            selectBodyText();
            url.value = 'https://example.com/new-tab';
            checkbox.checked = true;
            document.querySelector('#selectionLinkButton').click();
            const link = body.querySelector('a');
            const enabled = {target:link.target, rel:link.rel};

            const caret = document.createRange();
            caret.setStart(link.firstChild, 1);
            caret.collapse(true);
            getSelection().removeAllRanges();
            getSelection().addRange(caret);
            document.dispatchEvent(new Event('selectionchange'));
            const reflected = checkbox.checked;

            checkbox.checked = true;
            const plainText = document.createTextNode(' 通常本文');
            body.append(plainText);
            const plainCaret = document.createRange();
            plainCaret.setStart(plainText, 2);
            plainCaret.collapse(true);
            getSelection().removeAllRanges();
            getSelection().addRange(plainCaret);
            document.dispatchEvent(new Event('selectionchange'));
            const retainedOnPlainText = checkbox.checked;

            const linkRange = document.createRange();
            linkRange.selectNodeContents(link);
            getSelection().removeAllRanges();
            getSelection().addRange(linkRange);
            savedPreviewRange = linkRange.cloneRange();
            checkbox.checked = false;
            url.value = 'https://example.com/same-tab';
            document.querySelector('#selectionLinkButton').click();
            const updated = body.querySelector('a');
            const output = document.createElement('div');
            output.innerHTML = getPersistablePreviewHtml();
            return {
              label:label.textContent.trim(),
              immediatelyBeforeUnlink:label.nextElementSibling === unlink,
              enabled,
              reflected,
              retainedOnPlainText,
              disabledTarget:updated.getAttribute('target'),
              outputTarget:output.querySelector('a').getAttribute('target'),
              href:updated.getAttribute('href')
            };
        }""")
        self.assertEqual(result['label'], 'タブ化')
        self.assertTrue(result['immediatelyBeforeUnlink'])
        self.assertEqual(result['enabled']['target'], '_blank')
        self.assertIn('noopener', result['enabled']['rel'])
        self.assertTrue(result['reflected'])
        self.assertTrue(result['retainedOnPlainText'])
        self.assertIsNone(result['disabledTarget'])
        self.assertIsNone(result['outputTarget'])
        self.assertEqual(result['href'], 'https://example.com/same-tab')

    def test_delete_line_button_removes_caret_line_without_deleting_components(self):
        result = self.page.evaluate("""() => {
            const setCaret = (container, offset) => {
              const range = document.createRange();
              range.setStart(container, offset);
              range.collapse(true);
              const selection = getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
            };
            const button = document.querySelector('#selectionDeleteLineButton');

            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('note') + insertedComponentHtml('quote');
            const note = holder.children[0];
            const quote = holder.children[1];
            elements.preview.replaceChildren(note, document.createElement('br'), quote);
            setCaret(elements.preview, 2);
            button.click();
            const betweenParts = {
              components:[...elements.preview.children].map(item => item.dataset.insertedComponent),
              breaks:elements.preview.querySelectorAll(':scope > br').length
            };

            const body = document.createElement('div');
            body.dataset.insertedComponent = 'body';
            body.innerHTML = '一行目<br>削除行<br>三行目';
            applyDocumentBlockAppearance(body, {...readDocumentBlockSettings('body'), includeCard:false});
            elements.preview.replaceChildren(body);
            const targetText = [...body.childNodes].find(node => node.nodeType === Node.TEXT_NODE && node.nodeValue === '削除行');
            setCaret(targetText, 2);
            button.click();
            const bodyState = {text:body.innerText, breaks:body.querySelectorAll(':scope > br').length};

            const emptyBody = document.createElement('div');
            emptyBody.dataset.insertedComponent = 'body';
            emptyBody.append(document.createElement('br'));
            applyDocumentBlockAppearance(emptyBody, {...readDocumentBlockSettings('body'), includeCard:false});
            const secondNoteHolder = document.createElement('div');
            secondNoteHolder.innerHTML = insertedComponentHtml('note') + insertedComponentHtml('quote');
            const secondNote = secondNoteHolder.children[0];
            const secondQuote = secondNoteHolder.children[1];
            elements.preview.replaceChildren(secondNote, emptyBody, secondQuote);
            setCaret(emptyBody, 0);
            button.click();
            const emptyBodyRemoved = !emptyBody.isConnected;

            const protectedNoteHolder = document.createElement('div');
            protectedNoteHolder.innerHTML = insertedComponentHtml('note');
            const protectedNote = protectedNoteHolder.firstElementChild;
            elements.preview.replaceChildren(protectedNote);
            const original = protectedNote.textContent;
            setCaret(protectedNote.firstChild, 1);
            button.click();
            return {
              buttonInEditRow:!!button.closest('.component-edit-row'),
              betweenParts,
              bodyState,
              emptyBodyRemoved,
              protectedText:protectedNote.textContent,
              original,
              status:elements.status.textContent
            };
        }""")
        self.assertTrue(result['buttonInEditRow'])
        self.assertEqual(result['betweenParts']['components'], ['note', 'quote'])
        self.assertEqual(result['betweenParts']['breaks'], 0)
        self.assertEqual(result['bodyState']['text'], '一行目\n三行目')
        self.assertEqual(result['bodyState']['breaks'], 1)
        self.assertTrue(result['emptyBodyRemoved'])
        self.assertEqual(result['protectedText'], result['original'])
        self.assertIn('対象外', result['status'])

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
            const kinds = ['arrowDown','arrowUp','arrowRight','arrowLeft','triangleDown','triangleUp','triangleRight','triangleLeft',
              'chevronRight','chevronDown','doubleChevronRight','doubleChevronDown',
              'arrowBothHorizontal','arrowBothVertical','arrowTurnRight','arrowTurnLeft'];
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
        self.assertEqual([entry['text'] for entry in result],
                         ['↓','↑','→','←','▼','▲','▶','◀','❯','⌄','»','⌄⌄','⇄','⇅','↳','↲'])
        self.assertTrue(all(entry['noAdvancedCss'] for entry in result))

    def test_flow_shapes_preview_and_html_round_trip(self):
        result = self.page.evaluate("""() => {
            const expected = {
              chevronRight:'❯', chevronDown:'⌄', doubleChevronRight:'»', doubleChevronDown:'⌄⌄',
              arrowBothHorizontal:'⇄', arrowBothVertical:'⇅', arrowTurnRight:'↳', arrowTurnLeft:'↲'
            };
            const options = [...document.querySelectorAll('#shapeKind option')]
              .filter(option => Object.hasOwn(expected, option.value)).map(option => option.value);
            const states = Object.entries(expected).map(([kind, symbol]) => {
              elements.preview.innerHTML = shapeComponentHtml();
              let shape = elements.preview.firstElementChild;
              shape.dataset.shapeKind = kind;
              shape.dataset.shapeColor = '#ff0000';
              shape.dataset.shapeWidth = '90';
              shape.dataset.shapeHeight = '50';
              applyShapeDesign(shape);
              const preview = shape.querySelector('[data-shape-visual]');
              const previewState = {text:preview.textContent, color:preview.style.color,
                width:preview.getBoundingClientRect().width, height:preview.getBoundingClientRect().height};
              const html = formatOutputHtml(elements.preview.innerHTML);
              importArticleHtml(html);
              shape = elements.preview.querySelector('[data-inserted-component="shape"]');
              const restored = shape.querySelector('[data-shape-visual]');
              return {kind, symbol, preview:previewState, restored:restored.textContent,
                savedKind:shape.dataset.shapeKind, advanced:/clip-path|aspect-ratio/.test(html)};
            });
            return {options, states};
        }""")
        self.assertEqual(result['options'], [
            'chevronRight', 'chevronDown', 'doubleChevronRight', 'doubleChevronDown',
            'arrowBothHorizontal', 'arrowBothVertical', 'arrowTurnRight', 'arrowTurnLeft'])
        for state in result['states']:
            self.assertEqual(state['preview']['text'], state['symbol'])
            self.assertEqual(state['preview']['color'], 'rgb(255, 0, 0)')
            self.assertAlmostEqual(state['preview']['width'], 90, delta=1)
            self.assertGreaterEqual(state['preview']['height'], 50)
            self.assertEqual(state['restored'], state['symbol'])
            self.assertEqual(state['savedKind'], state['kind'])
            self.assertFalse(state['advanced'])

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
        types = ['heading', 'body', 'lead', 'list', 'note', 'quote', 'qa', 'table', 'image', 'imageText', 'imagePair',
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

    def test_pasted_markdown_and_html_can_be_saved_as_raw_text_backups(self):
        result = self.page.evaluate("""async () => {
            const records = [];
            Object.defineProperty(window, 'showSaveFilePicker', {configurable:true, value:async options => {
              const record = {options, text:null, mime:null, closed:false};
              records.push(record);
              return {name:options.suggestedName, async createWritable() { return {
                async write(blob) { record.text = await blob.text(); record.mime = blob.type; },
                async close() { record.closed = true; }
              }; }};
            }});
            const previewBefore = elements.preview.innerHTML;
            const savePaste = async (openId, modeName, textId, buttonId, text) => {
              document.getElementById(openId).click();
              const mode = document.querySelector(`input[name="${modeName}"][value="paste"]`);
              mode.checked = true;
              mode.dispatchEvent(new Event('change', {bubbles:true}));
              const textarea = document.getElementById(textId);
              textarea.value = text;
              document.getElementById(buttonId).click();
              const index = records.length - 1;
              while (!records[index]?.closed) await new Promise(resolve => setTimeout(resolve, 0));
              return {value:textarea.value,
                buttonText:document.getElementById(buttonId).textContent,
                visible:!document.getElementById(buttonId).closest('.markdown-import-panel').hidden,
                open:textarea.closest('dialog').open};
            };
            const markdown = `# 見出し

本文 **太字**
<script>raw only</script>`;
            const markdownUi = await savePaste('importMarkdownButton', 'markdownImportMode',
              'markdownPasteText', 'markdownPasteSaveButton', markdown);
            document.querySelector('#markdownImportDialog').close();
            const html = `<!-- backup -->
<section><h2>題名</h2><p>本文 &amp; 記号</p></section>`;
            const htmlUi = await savePaste('importHtmlButton', 'htmlImportMode',
              'htmlPasteText', 'htmlPasteSaveButton', html);
            document.querySelector('#htmlImportDialog').close();
            const countBeforeEmpty = records.length;
            const emptySaved = await savePastedTextBackup('   ',
              {type:'Markdown', extension:'md', mime:'text/markdown'});
            return {records, markdown, html, markdownUi, htmlUi, emptySaved,
              emptyCreated:records.length !== countBeforeEmpty,
              emptyStatus:elements.status.textContent,
              previewUnchanged:elements.preview.innerHTML === previewBefore,
              unsafeRan:window.raw === true};
        }""")
        self.assertEqual(len(result['records']), 2)
        markdown_record, html_record = result['records']
        self.assertRegex(markdown_record['options']['suggestedName'],
                         r'^p-player-markdown-backup-\d{8}-\d{6}\.md$')
        self.assertRegex(html_record['options']['suggestedName'],
                         r'^p-player-html-backup-\d{8}-\d{6}\.html$')
        self.assertEqual(markdown_record['options']['types'][0]['accept'], {'text/markdown': ['.md']})
        self.assertEqual(html_record['options']['types'][0]['accept'], {'text/html': ['.html']})
        self.assertEqual(markdown_record['text'], result['markdown'])
        self.assertEqual(html_record['text'], result['html'])
        self.assertEqual(markdown_record['mime'], 'text/markdown;charset=utf-8')
        self.assertEqual(html_record['mime'], 'text/html;charset=utf-8')
        for key, extension in [('markdownUi', '.md'), ('htmlUi', '.html')]:
            self.assertEqual(result[key]['value'], result['markdown' if key == 'markdownUi' else 'html'])
            self.assertIn(extension, result[key]['buttonText'])
            self.assertTrue(result[key]['visible'])
            self.assertTrue(result[key]['open'])
        self.assertFalse(result['emptySaved'])
        self.assertFalse(result['emptyCreated'])
        self.assertIn('Markdownテキストを貼り付けてください', result['emptyStatus'])
        self.assertTrue(result['previewUnchanged'])
        self.assertFalse(result['unsafeRan'])

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
        types = ["lead", "list", "note", "quote", "qa", "table", "image", "imageText", "imagePair",
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

    def test_large_lead_part_presets_settings_and_html_restore(self):
        result = self.page.evaluate("""() => {
            const insertIntoBody = (settings, text) => {
              const fragment = document.createDocumentFragment();
              fragment.append(text);
              const body = createDocumentBlockFromFragment('body', fragment, settings);
              elements.preview.replaceChildren(body);
              activeInsertedComponent = body;
              const range = document.createRange();
              range.selectNodeContents(body);
              range.collapse(false);
              const selection = getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
              insertComponentAtSelection('lead');
              return {body, lead:activeInsertedComponent, inside:body.contains(activeInsertedComponent)};
            };
            const formattedFragment = document.createDocumentFragment();
            const underline = document.createElement('u');
            underline.textContent = '前後';
            formattedFragment.append(underline);
            const formattedBody = createDocumentBlockFromFragment('body', formattedFragment, readDocumentBlockSettings('body'));
            elements.preview.replaceChildren(formattedBody);
            activeInsertedComponent = formattedBody;
            const formattedText = formattedBody.querySelector('u').firstChild;
            const formattedRange = document.createRange();
            formattedRange.setStart(formattedText, 1);
            formattedRange.collapse(true);
            getSelection().removeAllRanges();
            getSelection().addRange(formattedRange);
            savedPreviewRange = formattedRange.cloneRange();
            insertComponentAtSelection('lead');
            const splitLead = activeInsertedComponent;
            const splitFormatting = {
              nestedInUnderline:!!splitLead.closest('u'),
              leadInsideBody:formattedBody.contains(splitLead),
              underlinedText:[...formattedBody.querySelectorAll('u')].map(item => item.textContent).join('|')
            };
            const plainResult = insertIntoBody(readDocumentBlockSettings('body'), '通常本文');
            const cardResult = insertIntoBody(bodySettingsForMode('card'), '本文カード');
            const body = cardResult.body;
            const lead = cardResult.lead;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const preset = document.querySelector('#leadPreset');
            const states = {};
            for (const value of ['accent', 'lines', 'band', 'frame', 'quote', 'underline', 'dotted', 'badgeSolid', 'badgeOutline', 'badgeTag', 'badgeStamp', 'centered']) {
              preset.value = value;
              preset.dispatchEvent(new Event('change', {bubbles:true}));
              states[value] = {
                left:lead.style.borderLeftWidth,
                top:lead.style.borderTopWidth,
                bottom:lead.style.borderBottomWidth,
                style:lead.style.borderTopStyle || lead.style.borderLeftStyle || lead.style.borderBottomStyle,
                radius:lead.style.borderRadius,
                width:lead.style.width,
                maxWidth:lead.style.maxWidth,
                marginLeft:lead.style.marginLeft,
                marginRight:lead.style.marginRight,
                marginTop:lead.style.marginTop,
                marginBottom:lead.style.marginBottom,
                background:lead.style.backgroundColor,
                fontStyle:lead.querySelector('[data-lead-content]').style.fontStyle,
                align:lead.querySelector('[data-lead-content]').style.textAlign
              };
            }
            preset.value = 'band';
            preset.dispatchEvent(new Event('change', {bubbles:true}));
            body.style.textDecoration = 'underline';
            const inheritedDecoration = getComputedStyle(lead.querySelector('[data-lead-content]')).textDecorationLine;
            lead.querySelector('[data-lead-content]').innerHTML = '<u data-explicit-underline>明示的な下線</u>';
            const explicitDecoration = getComputedStyle(lead.querySelector('[data-explicit-underline]')).textDecorationLine;
            document.querySelector('#leadSize').value = '40';
            document.querySelector('#leadMaxWidth').value = '70';
            document.querySelector('#leadPlacement').value = 'right';
            document.querySelector('#leadLineHeight').value = '1.8';
            document.querySelector('#leadColorText').value = '#334155';
            document.querySelector('#leadAccentText').value = '#dc2626';
            document.querySelector('#leadSize').dispatchEvent(new Event('input', {bubbles:true}));
            const content = lead.querySelector('[data-lead-content]');
            content.innerHTML = '<strong>大型リード文</strong><br>補足メッセージ';
            const custom = {
              preset:lead.dataset.leadPreset,
              fontSize:content.style.fontSize,
              width:lead.style.width,
              marginLeft:lead.style.marginLeft,
              marginRight:lead.style.marginRight,
              lineHeight:content.style.lineHeight,
              color:content.style.color,
              accent:lead.dataset.leadAccent,
              decoration:lead.dataset.leadDecoration
            };
            const exported = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(exported, 'lead.html');
            const restored = elements.preview.querySelector('[data-inserted-component="lead"]');
            return {
              menu:[...document.querySelectorAll('#componentInsertSelect option')].some(option => option.value === 'lead'),
              quick:!!document.querySelector('.component-quick-button[data-component-type="lead"]'),
              insidePlainBody:plainResult.inside,
              insideBodyCard:cardResult.inside,
              splitFormatting,
              states,
              inheritedDecoration,
              explicitDecoration,
              custom,
              restored:!!restored,
              restoredText:restored?.querySelector('[data-lead-content]')?.innerText,
              restoredEditable:restored?.querySelector('[data-lead-content]')?.getAttribute('contenteditable'),
              restoredDecoration:restored?.querySelector('[data-lead-content]')?.style.textDecoration,
              isHeading:!!restored?.querySelector('h1,h2,h3,h4,h5,h6')
            };
        }""")
        self.assertTrue(result["menu"])
        self.assertTrue(result["quick"])
        self.assertTrue(result["insidePlainBody"])
        self.assertTrue(result["insideBodyCard"])
        self.assertFalse(result["splitFormatting"]["nestedInUnderline"])
        self.assertTrue(result["splitFormatting"]["leadInsideBody"])
        self.assertEqual(result["splitFormatting"]["underlinedText"], "前|後")
        self.assertEqual(result["states"]["accent"]["left"], "6px")
        self.assertEqual(result["states"]["accent"]["align"], "left")
        self.assertEqual(result["states"]["lines"]["top"], "2px")
        self.assertEqual(result["states"]["lines"]["bottom"], "2px")
        self.assertEqual(result["states"]["band"]["radius"], "8px")
        self.assertNotEqual(result["states"]["band"]["background"], "")
        self.assertEqual(result["states"]["frame"]["top"], "2px")
        self.assertEqual(result["states"]["frame"]["radius"], "10px")
        self.assertEqual(result["states"]["quote"]["left"], "5px")
        self.assertEqual(result["states"]["quote"]["fontStyle"], "italic")
        self.assertEqual(result["states"]["underline"]["bottom"], "5px")
        self.assertEqual(result["states"]["dotted"]["style"], "dotted")
        self.assertEqual(result["states"]["dotted"]["bottom"], "3px")
        self.assertEqual(result["states"]["badgeSolid"]["width"], "fit-content")
        self.assertEqual(result["states"]["badgeSolid"]["radius"], "999px")
        self.assertNotEqual(result["states"]["badgeSolid"]["background"], "")
        self.assertEqual(result["states"]["badgeSolid"]["marginLeft"], "0px")
        self.assertEqual(result["states"]["badgeSolid"]["marginRight"], "auto")
        self.assertEqual(result["states"]["badgeSolid"]["marginTop"], "10px")
        self.assertEqual(result["states"]["badgeSolid"]["marginBottom"], "10px")
        self.assertEqual(result["states"]["badgeOutline"]["top"], "2px")
        self.assertEqual(result["states"]["badgeOutline"]["radius"], "999px")
        self.assertEqual(result["states"]["badgeTag"]["left"], "7px")
        self.assertEqual(result["states"]["badgeStamp"]["top"], "4px")
        self.assertEqual(result["states"]["badgeStamp"]["style"], "double")
        self.assertEqual(result["states"]["centered"]["align"], "center")
        self.assertEqual(result["states"]["centered"]["marginTop"], "10px")
        self.assertEqual(result["states"]["centered"]["marginBottom"], "10px")
        self.assertEqual(result["states"]["accent"]["marginTop"], "10px")
        self.assertEqual(result["states"]["lines"]["marginBottom"], "10px")
        self.assertEqual(result["inheritedDecoration"], "none")
        self.assertEqual(result["explicitDecoration"], "underline")
        self.assertEqual(result["custom"]["preset"], "custom")
        self.assertIn("40px", result["custom"]["fontSize"])
        self.assertEqual(result["custom"]["width"], "70%")
        self.assertEqual(result["custom"]["marginLeft"], "auto")
        self.assertEqual(result["custom"]["marginRight"], "0px")
        self.assertEqual(result["custom"]["lineHeight"], "1.8")
        self.assertIn("51, 65, 85", result["custom"]["color"])
        self.assertEqual(result["custom"]["accent"], "#dc2626")
        self.assertEqual(result["custom"]["decoration"], "band")
        self.assertTrue(result["restored"])
        self.assertEqual(result["restoredText"], "大型リード文\n補足メッセージ")
        self.assertEqual(result["restoredEditable"], "true")
        self.assertEqual(result["restoredDecoration"], "none")
        self.assertFalse(result["isHeading"])

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

    def test_before_after_supports_three_step_flow_and_restores_middle(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('beforeAfter');
            const component = elements.preview.firstElementChild;
            activeInsertedComponent = component;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const count = document.querySelector('#compareCount');
            const arrow = document.querySelector('#compareArrow');
            const layout = document.querySelector('#compareLayout');
            const cards = () => [...component.children].filter(el => !el.hasAttribute('data-compare-arrow'));
            const arrows = () => [...component.querySelectorAll(':scope > [data-compare-arrow]')];
            const initial = {count:count.value, cards:cards().length};
            count.value = '3';
            count.dispatchEvent(new Event('input', {bubbles:true}));
            arrow.checked = true;
            arrow.dispatchEvent(new Event('input', {bubbles:true}));
            const middle = cards()[1];
            middle.innerHTML = '<strong>試作</strong><br>中間データ';
            capturePreviewEdits();
            const horizontal = {
              count:component.dataset.compareCount,
              cards:cards().length,
              arrows:arrows().map(el => el.textContent),
              stages:cards().map(el => el.dataset.compareStage),
              columns:component.style.gridTemplateColumns
            };
            count.value = '2';
            count.dispatchEvent(new Event('input', {bubbles:true}));
            const reduced = {cards:cards().length, saved:component.dataset.compareMiddleHtml};
            count.value = '3';
            count.dispatchEvent(new Event('input', {bubbles:true}));
            layout.value = 'vertical';
            layout.dispatchEvent(new Event('input', {bubbles:true}));
            const restoredMiddle = cards()[1].innerHTML;
            const verticalArrows = arrows().map(el => el.textContent);
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const imported = elements.preview.querySelector('[data-inserted-component="beforeAfter"]');
            return {initial, horizontal, reduced, restoredMiddle, verticalArrows,
              importedCount:imported.dataset.compareCount,
              importedCards:[...imported.children].filter(el => !el.hasAttribute('data-compare-arrow')).length,
              importedArrows:imported.querySelectorAll(':scope > [data-compare-arrow]').length};
        }""")
        self.assertEqual(result['initial'], {'count': '2', 'cards': 2})
        self.assertEqual(result['horizontal']['count'], '3')
        self.assertEqual(result['horizontal']['cards'], 3)
        self.assertEqual(result['horizontal']['arrows'], ['→', '→'])
        self.assertEqual(result['horizontal']['stages'], ['before', 'middle', 'after'])
        self.assertIn('auto', result['horizontal']['columns'])
        self.assertEqual(result['reduced']['cards'], 2)
        self.assertIn('中間データ', result['reduced']['saved'])
        self.assertIn('中間データ', result['restoredMiddle'])
        self.assertEqual(result['verticalArrows'], ['↓', '↓'])
        self.assertEqual(result['importedCount'], '3')
        self.assertEqual(result['importedCards'], 3)
        self.assertEqual(result['importedArrows'], 2)

    def test_compare_triangle_arrows_save_import_and_switch_direction(self):
        result = self.page.evaluate("""() => {
          elements.preview.innerHTML = insertedComponentHtml('beforeAfter');
          const sync = () => {
            activeInsertedComponent = elements.preview.querySelector('[data-inserted-component="beforeAfter"]');
            document.querySelector('.inserted-component-properties')._sync();
          };
          const set = (id, value) => {
            const input = document.getElementById(id);
            if (input.type === 'checkbox') input.checked = value;
            else input.value = value;
            input.dispatchEvent(new Event('input', {bubbles:true}));
          };
          const arrows = () => [...elements.preview.querySelectorAll(
            '[data-inserted-component="beforeAfter"] > [data-compare-arrow]')].map(el => el.textContent.trim());
          sync();
          const initial = document.querySelector('#compareArrowStyle').value;
          set('compareCount', '3');
          set('compareArrow', true);
          const normal = arrows();
          set('compareArrowStyle', 'triangle');
          const horizontal = arrows();
          set('compareLayout', 'vertical');
          const vertical = arrows();
          applyArticlePayload({saveType:'full', settings:{}, articleHtml:getPersistablePreviewHtml()});
          sync();
          const json = {style:document.querySelector('#compareArrowStyle').value, arrows:arrows()};
          importArticleHtml(formatOutputHtml(getPersistablePreviewHtml()));
          sync();
          const html = {style:document.querySelector('#compareArrowStyle').value, arrows:arrows()};
          set('compareArrow', false);
          const disabled = {count:arrows().length, control:document.querySelector('#compareArrowStyle').disabled};
          set('compareArrow', true);
          set('compareLayout', 'horizontal');
          const restored = arrows();
          set('compareArrowStyle', 'arrow');
          set('compareLayout', 'vertical');
          return {initial, normal, horizontal, vertical, json, html, disabled, restored, final:arrows()};
        }""")
        self.assertEqual(result['initial'], 'arrow')
        self.assertEqual(result['normal'], ['→', '→'])
        self.assertEqual(result['horizontal'], ['▶', '▶'])
        self.assertEqual(result['vertical'], ['▼', '▼'])
        for key in ('json', 'html'):
            self.assertEqual(result[key], dict(style='triangle', arrows=['▼', '▼']))
        self.assertEqual(result['disabled'], dict(count=0, control=True))
        self.assertEqual(result['restored'], ['▶', '▶'])
        self.assertEqual(result['final'], ['↓', '↓'])

    def test_vertical_flow_width_alignment_and_round_trip(self):
        result = self.page.evaluate("""() => {
          elements.preview.innerHTML = insertedComponentHtml('beforeAfter');
          let component = elements.preview.firstElementChild;
          const sync = () => {
            activeInsertedComponent = component;
            document.querySelector('.inserted-component-properties')._sync();
          };
          const set = (id, value) => {
            const input = document.getElementById(id);
            if (input.type === 'checkbox') input.checked = value;
            else input.value = value;
            input.dispatchEvent(new Event('input', {bubbles:true}));
          };
          sync();
          const row = document.querySelector('[data-compare-vertical-settings]');
          const initial = {hidden:row.hidden, width:document.querySelector('#compareVerticalWidth').value};
          set('compareCount', '3');
          set('compareLayout', 'vertical');
          set('compareArrow', true);
          set('compareVerticalWidth', '60');
          const placements = ['left','center','right'].map(align => {
            set('compareVerticalAlign', align);
            const rect = component.getBoundingClientRect();
            const parent = elements.preview.getBoundingClientRect();
            const card = component.querySelector('[data-compare-stage]').getBoundingClientRect();
            const arrow = component.querySelector(':scope > [data-compare-arrow]').getBoundingClientRect();
            return {align, x:rect.x, width:rect.width, cardWidth:card.width,
              centered:Math.abs(arrow.x + arrow.width / 2 - (rect.x + rect.width / 2)) < 1,
              visible:!row.hidden};
          });
          const saved = getPersistablePreviewHtml();
          applyArticlePayload({saveType:'full', settings:{}, articleHtml:saved});
          component = elements.preview.querySelector('[data-inserted-component="beforeAfter"]');
          sync();
          const jsonWidth = component.style.width;
          importArticleHtml(formatOutputHtml(getPersistablePreviewHtml()));
          component = elements.preview.querySelector('[data-inserted-component="beforeAfter"]');
          sync();
          const restored = {width:document.querySelector('#compareVerticalWidth').value,
            align:document.querySelector('#compareVerticalAlign').value,
            css:component.style.width, margin:component.style.marginLeft};
          set('compareLayout', 'horizontal');
          const horizontal = {width:component.style.width, hidden:row.hidden};
          set('compareLayout', 'vertical');
          return {initial, placements, jsonWidth, restored, horizontal,
            back:component.style.width, backAlign:component.dataset.compareVerticalAlign};
        }""")
        self.assertEqual(result['initial'], dict(hidden=True, width='100'))
        placements = result['placements']
        self.assertLess(placements[0]['x'], placements[1]['x'])
        self.assertLess(placements[1]['x'], placements[2]['x'])
        for placement in placements:
            self.assertTrue(placement['centered'])
            self.assertTrue(placement['visible'])
            self.assertAlmostEqual(placement['width'], placement['cardWidth'], delta=1)
        self.assertEqual(result['jsonWidth'], '60%')
        self.assertEqual(result['restored'], dict(width='60', align='right', css='60%', margin='auto'))
        self.assertEqual(result['horizontal'], dict(width='', hidden=True))
        self.assertEqual(result['back'], '60%')
        self.assertEqual(result['backAlign'], 'right')

    def test_compare_arrows_are_isolated_from_parent_underline(self):
        for direction, symbol in [('horizontal', '→'), ('vertical', '↓')]:
            result = self.page.evaluate("""({direction, symbol}) => {
                elements.preview.innerHTML = '<div style="text-decoration:underline">'
                  + insertedComponentHtml('beforeAfter') + '</div>';
                const component = elements.preview.querySelector('[data-inserted-component="beforeAfter"]');
                activeInsertedComponent = component;
                document.querySelector('.inserted-component-properties')._sync();
                const layout = document.querySelector('#compareLayout');
                layout.value = direction;
                layout.dispatchEvent(new Event('input', {bubbles:true}));
                const flag = document.querySelector('#compareArrow');
                flag.checked = true;
                flag.dispatchEvent(new Event('input', {bubbles:true}));
                const inspect = root => {
                  const arrow = root.querySelector('[data-inserted-component="beforeAfter"] > [data-compare-arrow]');
                  const glyph = arrow.querySelector('[data-compare-arrow-glyph]');
                  return {text:arrow.textContent.trim(), display:glyph?.style.display,
                    decoration:glyph?.style.textDecoration,
                    parent:[...root.querySelectorAll('[style]')].some(el =>
                      el.contains(arrow) && el.style.textDecorationLine === 'underline')};
                };
                // Simulate an older save, without the isolation wrapper.
                const arrow = component.querySelector('[data-compare-arrow="true"]');
                arrow.textContent = symbol;
                capturePreviewEdits();
                const preview = inspect(elements.preview);
                const exported = document.createElement('div');
                const html = formatOutputHtml(getPersistablePreviewHtml());
                exported.innerHTML = html;
                const output = inspect(exported);
                importArticleHtml(html);
                return {preview, output, imported:inspect(elements.preview)};
            }""", dict(direction=direction, symbol=symbol))
            for state in result.values():
                self.assertEqual(state, dict(text=symbol, display='inline-block', decoration='none', parent=True))

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

    def test_four_image_gallery_preserves_fourth_image_link_and_caption(self):
        result = self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('imagePair');
            elements.preview.replaceChildren(holder.firstElementChild);
            activeInsertedComponent = elements.preview.firstElementChild;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const count = document.querySelector('#componentImagePairCount');
            count.value = '4';
            count.dispatchEvent(new Event('change', {bubbles:true}));
            const path = document.querySelector('#componentImagePath4');
            path.value = 'https://example.com/four.png';
            path.dispatchEvent(new Event('input', {bubbles:true}));
            const link = document.querySelector('#componentImageLinkUrl4');
            link.value = 'https://example.com/four';
            link.dispatchEvent(new Event('input', {bubbles:true}));
            const captionToggle = document.querySelector('#componentImageCaption4');
            captionToggle.checked = true;
            captionToggle.dispatchEvent(new Event('change', {bubbles:true}));
            activeInsertedComponent.children[3].querySelector('[data-image-caption]').textContent = 'fourth caption';
            count.value = '2';
            count.dispatchEvent(new Event('change', {bubbles:true}));
            count.value = '4';
            count.dispatchEvent(new Event('change', {bubbles:true}));
            const images = activeInsertedComponent.querySelectorAll('img[data-inserted-image]');
            return {
              count:images.length,
              pairCount:activeInsertedComponent.dataset.imagePairCount,
              fourthSrc:images[3].dataset.securitySrc || images[3].getAttribute('src'),
              fourthLink:images[3].parentElement.getAttribute('href'),
              fourthCaption:activeInsertedComponent.children[3].querySelector('[data-image-caption]')?.textContent,
              grid:activeInsertedComponent.style.gridTemplateColumns
            };
        }""")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["pairCount"], "4")
        self.assertEqual(result["fourthSrc"], "https://example.com/four.png")
        self.assertEqual(result["fourthLink"], "https://example.com/four")
        self.assertEqual(result["fourthCaption"], "fourth caption")
        self.assertIn("repeat(4", result["grid"])

    def test_point_card_list_uses_number_badges_and_keeps_them_when_customized(self):
        result = self.page.evaluate("""() => {
            const holder = document.createElement('div');
            holder.innerHTML = insertedComponentHtml('list');
            elements.preview.replaceChildren(holder.firstElementChild);
            activeInsertedComponent = elements.preview.firstElementChild;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const preset = document.querySelector('#listDesignPreset');
            const badgeStyleField = document.querySelector('#listNumberBadgeStyle').closest('.field');
            const lineBreakHelp = badgeStyleField.nextElementSibling;
            preset.value = 'cards';
            preset.dispatchEvent(new Event('change', {bubbles:true}));
            const start = document.querySelector('#listStartNumber');
            start.value = '4';
            start.dispatchEvent(new Event('input', {bubbles:true}));
            const markers = [...activeInsertedComponent.querySelectorAll('[data-list-marker-part]')];
            const style = document.querySelector('#listNumberBadgeStyle');
            const defaultStyle = style.value;
            const designs = {};
            for (const value of ['solidCircle', 'outlineCircle', 'roundedSquare', 'label']) {
              style.value = value;
              style.dispatchEvent(new Event('change', {bubbles:true}));
              const marker = activeInsertedComponent.querySelector('[data-list-marker-part]');
              designs[value] = {text:marker.textContent, background:marker.style.backgroundColor,
                border:marker.style.borderStyle, radius:marker.style.borderRadius};
            }
            return {
              preset:preset.value,
              badge:activeInsertedComponent.dataset.listNumberBadge,
              texts:markers.map(marker => marker.textContent),
              defaultStyle,
              designs,
              savedStyle:activeInsertedComponent.dataset.listNumberBadgeStyle,
              lineBreakHelp:lineBreakHelp?.textContent.trim(),
              helpIsRightAfterStyle:lineBreakHelp?.classList.contains('list-line-break-help')
            };
        }""")
        self.assertEqual(result["preset"], "custom")
        self.assertEqual(result["badge"], "true")
        self.assertEqual(result["defaultStyle"], "roundedSquare")
        self.assertEqual(result["designs"]["solidCircle"]["text"], "4")
        self.assertTrue(result["designs"]["solidCircle"]["background"])
        self.assertEqual(result["designs"]["outlineCircle"]["background"], "transparent")
        self.assertEqual(result["designs"]["outlineCircle"]["border"], "solid")
        self.assertNotEqual(result["designs"]["roundedSquare"]["radius"], "999px")
        self.assertEqual(result["designs"]["label"]["text"], "POINT 4")
        self.assertEqual(result["savedStyle"], "label")
        self.assertEqual(result["lineBreakHelp"], "Shift + Enterでグループ内で改行できます")
        self.assertTrue(result["helpIsRightAfterStyle"])

    def test_half_height_text_marker_applies_persists_and_toggles_off(self):
        result = self.page.evaluate("""() => {
            const body = document.createElement('div');
            body.dataset.insertedComponent = 'body';
            body.contentEditable = 'true';
            body.textContent = '下半分マーカー';
            elements.preview.replaceChildren(body);
            const styleControl = document.querySelector('#selectionHighlightStyle');
            styleControl.value = 'half';
            styleControl.dispatchEvent(new Event('change', {bubbles:true}));
            const previewHalf = document.querySelector('#selectionHighlightColorPreview').style.backgroundImage;
            const swatchHalf = document.querySelector('#selectionHighlightPalette [data-marker-color]').style.backgroundImage;
            styleControl.value = 'full';
            styleControl.dispatchEvent(new Event('change', {bubbles:true}));
            const previewFull = document.querySelector('#selectionHighlightColorPreview').style.backgroundImage;
            styleControl.value = 'half';
            styleControl.dispatchEvent(new Event('change', {bubbles:true}));
            const selectContents = (target) => {
              const range = document.createRange();
              range.selectNodeContents(target);
              const selection = getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
            };
            selectContents(body);
            applySelectionFormat('hiliteColor', '#fef08a', {forceApply:true, markerStyle:'half'});
            const marker = body.querySelector('[data-half-highlight="true"]');
            const saved = getPersistablePreviewHtml();
            const sanitized = sanitizeArticleMarkup(saved);
            const state = {
              styleOptions:[...document.querySelectorAll('#selectionHighlightStyle option')].map(option => option.value),
              previewHalf, swatchHalf, previewFull,
              text:marker?.textContent,
              image:marker?.style.backgroundImage,
              repeat:marker?.style.backgroundRepeat,
              saved:saved.includes('data-half-highlight="true"'),
              sanitized:sanitized.includes('data-half-highlight="true"')
            };
            selectContents(marker);
            resetSelectionFormatting();
            state.resetRemoved = !body.querySelector('[data-half-highlight="true"]');
            state.resetText = body.textContent;
            selectContents(body);
            applySelectionFormat('hiliteColor', '#fef08a', {forceApply:true, markerStyle:'half'});
            const reappliedMarker = body.querySelector('[data-half-highlight="true"]');
            selectContents(reappliedMarker);
            applySelectionFormat('hiliteColor', '#fef08a', {markerStyle:'half'});
            state.removed = !body.querySelector('[data-half-highlight="true"]');
            state.remainingText = body.textContent;
            return state;
        }""")
        self.assertEqual(result["styleOptions"], ["full", "half"])
        self.assertIn("linear-gradient", result["previewHalf"])
        self.assertIn("linear-gradient", result["swatchHalf"])
        self.assertNotIn("linear-gradient", result["previewFull"])
        self.assertEqual(result["text"], "下半分マーカー")
        self.assertIn("linear-gradient", result["image"])
        self.assertIn("50%", result["image"])
        self.assertEqual(result["repeat"], "no-repeat")
        self.assertTrue(result["saved"])
        self.assertTrue(result["sanitized"])
        self.assertTrue(result["resetRemoved"])
        self.assertEqual(result["resetText"], "下半分マーカー")
        self.assertTrue(result["removed"])
        self.assertEqual(result["remainingText"], "下半分マーカー")

    def test_reselected_markers_can_be_overwritten_and_removed(self):
        result = self.page.evaluate("""() => {
            const body = document.createElement('div');
            body.dataset.insertedComponent = 'body';
            body.contentEditable = 'true';
            body.textContent = '再選択マーカー';
            elements.preview.replaceChildren(body);
            const selectContents = (target) => {
              const range = document.createRange();
              range.selectNodeContents(target);
              const selection = getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
            };
            const fullMarker = () => [...body.querySelectorAll('span, font, mark')].find((element) => {
              const color = element.style.backgroundColor;
              return color && color !== 'transparent' && color !== 'rgba(0, 0, 0, 0)';
            });
            selectContents(body);
            applySelectionFormat('hiliteColor', '#fef08a', {forceApply:true, markerStyle:'full'});
            selectContents(fullMarker());
            applySelectionFormat('hiliteColor', '#7dd3fc', {forceApply:true, markerStyle:'full'});
            const fullOverwrite = fullMarker()?.style.backgroundColor;
            selectContents(fullMarker());
            applySelectionFormat('hiliteColor', '#7dd3fc', {markerStyle:'full'});
            const fullRemoved = !fullMarker();

            selectContents(body);
            applySelectionFormat('hiliteColor', '#fef08a', {forceApply:true, markerStyle:'half'});
            selectContents(body.querySelector('[data-half-highlight="true"]'));
            applySelectionFormat('hiliteColor', '#7dd3fc', {forceApply:true, markerStyle:'half'});
            const halfOverwrite = body.querySelector('[data-half-highlight="true"]')?.style.backgroundImage;
            selectContents(body.querySelector('[data-half-highlight="true"]'));
            applySelectionFormat('hiliteColor', '#7dd3fc', {markerStyle:'half'});
            return {
              fullOverwrite,
              fullRemoved,
              halfOverwrite,
              halfRemoved:!body.querySelector('[data-half-highlight="true"]'),
              text:body.textContent
            };
        }""")
        self.assertIn("125, 211, 252", result["fullOverwrite"])
        self.assertTrue(result["fullRemoved"])
        self.assertIn("125, 211, 252", result["halfOverwrite"])
        self.assertNotIn("254, 240, 138", result["halfOverwrite"])
        self.assertTrue(result["halfRemoved"])
        self.assertEqual(result["text"], "再選択マーカー")

    def test_marker_changes_are_limited_to_the_reselected_characters(self):
        result = self.page.evaluate("""() => {
            const body = document.createElement('div');
            body.dataset.insertedComponent = 'body';
            body.contentEditable = 'true';
            elements.preview.replaceChildren(body);
            const selectText = (start, end) => {
              const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
              let node;
              let offset = 0;
              let startNode, startOffset, endNode, endOffset;
              while ((node = walker.nextNode())) {
                const next = offset + node.length;
                if (!startNode && start >= offset && start <= next) {
                  startNode = node; startOffset = start - offset;
                }
                if (!endNode && end >= offset && end <= next) {
                  endNode = node; endOffset = end - offset; break;
                }
                offset = next;
              }
              const range = document.createRange();
              range.setStart(startNode, startOffset);
              range.setEnd(endNode, endOffset);
              const selection = getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
            };
            const decorations = () => {
              const values = [];
              const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                for (const character of node.nodeValue) {
                  let element = node.parentElement;
                  let value = 'none';
                  while (element && body.contains(element)) {
                    if (element.dataset.halfHighlight === 'true') {
                      value = element.style.backgroundImage; break;
                    }
                    if (element.style.backgroundColor && element.style.backgroundColor !== 'transparent') {
                      value = element.style.backgroundColor; break;
                    }
                    element = element.parentElement;
                  }
                  values.push({character, value});
                }
              }
              return values;
            };

            body.textContent = 'ABCDE';
            selectText(0, 5);
            applySelectionFormat('hiliteColor', '#fef08a', {forceApply:true, markerStyle:'full'});
            selectText(1, 3);
            applySelectionFormat('hiliteColor', '#7dd3fc', {forceApply:true, markerStyle:'full'});
            const fullOverwrite = decorations();
            selectText(1, 2);
            applySelectionFormat('hiliteColor', '#7dd3fc', {markerStyle:'full'});
            const fullRemove = decorations();

            body.textContent = 'ABCDE';
            selectText(0, 5);
            applySelectionFormat('hiliteColor', '#fef08a', {forceApply:true, markerStyle:'half'});
            selectText(1, 3);
            applySelectionFormat('hiliteColor', '#7dd3fc', {forceApply:true, markerStyle:'half'});
            const halfOverwrite = decorations();
            selectText(1, 2);
            applySelectionFormat('hiliteColor', '#7dd3fc', {markerStyle:'half'});
            return {fullOverwrite, fullRemove, halfOverwrite, halfRemove:decorations(), text:body.textContent};
        }""")
        def values(state):
            return [item["value"] for item in result[state]]

        full_overwrite = values("fullOverwrite")
        self.assertIn("254, 240, 138", full_overwrite[0])
        self.assertIn("125, 211, 252", full_overwrite[1])
        self.assertIn("125, 211, 252", full_overwrite[2])
        self.assertIn("254, 240, 138", full_overwrite[3])
        full_remove = values("fullRemove")
        self.assertEqual(full_remove[1], "none")
        self.assertIn("125, 211, 252", full_remove[2])
        half_overwrite = values("halfOverwrite")
        self.assertIn("254, 240, 138", half_overwrite[0])
        self.assertIn("125, 211, 252", half_overwrite[1])
        self.assertIn("125, 211, 252", half_overwrite[2])
        self.assertIn("254, 240, 138", half_overwrite[3])
        half_remove = values("halfRemove")
        self.assertEqual(half_remove[1], "none")
        self.assertIn("125, 211, 252", half_remove[2])
        self.assertEqual(result["text"], "ABCDE")

    def test_marker_palette_only_selects_color_until_marker_button_is_pressed(self):
        result = self.page.evaluate("""() => {
            const body = document.createElement('div');
            body.dataset.insertedComponent = 'body';
            body.contentEditable = 'true';
            body.textContent = 'パレット操作';
            elements.preview.replaceChildren(body);
            const selectContents = (target) => {
              const range = document.createRange();
              range.selectNodeContents(target);
              const selection = getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              savedPreviewRange = range.cloneRange();
            };
            const marker = () => [...body.querySelectorAll('span, font, mark')].find((element) => {
              const color = element.style.backgroundColor;
              return color && color !== 'transparent' && color !== 'rgba(0, 0, 0, 0)';
            });
            const markerButton = document.querySelector('#selectionHighlightButton');
            const colorButton = document.querySelector('#selectionHighlightColorButton');
            const swatches = [...document.querySelectorAll('#selectionHighlightPalette [data-marker-color]')];
            const colorInput = document.querySelector('#selectionHighlightColor');

            selectContents(body);
            colorButton.click();
            const afterPaletteButton = !marker();
            swatches[0].click();
            const afterSwatch = !marker();
            colorInput.value = '#7dd3fc';
            colorInput.dispatchEvent(new Event('input', {bubbles:true}));
            colorInput.dispatchEvent(new Event('change', {bubbles:true}));
            const afterCustomColor = !marker();
            markerButton.click();
            const appliedColor = marker()?.style.backgroundColor;

            selectContents(marker());
            swatches[1].click();
            const beforeOverwrite = marker()?.style.backgroundColor;
            markerButton.click();
            const overwrittenMarker = marker();
            const overwrittenColor = overwrittenMarker?.style.backgroundColor;
            selectContents(overwrittenMarker);
            markerButton.click();
            return {
              afterPaletteButton,
              afterSwatch,
              afterCustomColor,
              appliedColor,
              beforeOverwrite,
              overwrittenColor,
              removed:!marker(),
              transparentSwatches:document.querySelectorAll('#selectionHighlightPalette .is-transparent').length
            };
        }""")
        self.assertTrue(result["afterPaletteButton"])
        self.assertTrue(result["afterSwatch"])
        self.assertTrue(result["afterCustomColor"])
        self.assertIn("125, 211, 252", result["appliedColor"])
        self.assertEqual(result["beforeOverwrite"], result["appliedColor"])
        self.assertNotEqual(result["overwrittenColor"], result["appliedColor"])
        self.assertTrue(result["removed"])
        self.assertEqual(result["transparentSwatches"], 0)

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

    def test_table_radius_is_visible_and_survives_round_trip(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('table');
            const table = elements.preview.querySelector('table');
            activeInsertedComponent = table;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const radius = document.querySelector('#tableRadius');
            radius.value = '14';
            radius.dispatchEvent(new Event('input', {bubbles:true}));
            const first = table.rows[0].cells[0];
            const last = table.rows[table.rows.length - 1].cells[table.rows[table.rows.length - 1].cells.length - 1];
            const rounded = {
              radius:table.style.borderRadius,
              collapse:table.style.borderCollapse,
              spacing:table.style.borderSpacing,
              overflow:table.style.overflow,
              first:first.style.borderTopLeftRadius,
              last:last.style.borderBottomRightRadius,
              innerRight:first.style.borderRightWidth,
              nextLeft:table.rows[0].cells[1].style.borderLeftWidth
            };
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const restored = elements.preview.querySelector('table');
            const restoredState = {
              radius:restored.style.borderRadius,
              collapse:restored.style.borderCollapse,
              first:restored.rows[0].cells[0].style.borderTopLeftRadius
            };
            activeInsertedComponent = restored;
            properties._sync();
            radius.value = '0';
            radius.dispatchEvent(new Event('input', {bubbles:true}));
            return {rounded, restored:restoredState, square:{
              collapse:restored.style.borderCollapse,
              overflow:restored.style.overflow,
              first:restored.rows[0].cells[0].style.borderTopLeftRadius,
              right:restored.rows[0].cells[0].style.borderRightWidth
            }};
        }""")
        self.assertEqual(result['rounded'], {
            'radius': '14px', 'collapse': 'separate', 'spacing': '0px',
            'overflow': 'hidden', 'first': '14px', 'last': '14px',
            'innerRight': '0px', 'nextLeft': '1px'})
        self.assertEqual(result['restored'], {
            'radius': '14px', 'collapse': 'separate', 'first': '14px'})
        self.assertEqual(result['square'], {
            'collapse': 'collapse', 'overflow': '', 'first': '0px', 'right': '1px'})

    def test_table_inner_vertical_and_horizontal_lines_can_be_hidden(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('table');
            const table = elements.preview.querySelector('table');
            activeInsertedComponent = table;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const vertical = document.querySelector('#tableInnerVerticalLines');
            const horizontal = document.querySelector('#tableInnerHorizontalLines');
            const verticalRect = vertical.closest('label').getBoundingClientRect();
            const horizontalRect = horizontal.closest('label').getBoundingClientRect();
            const sameSettingsRow = Math.abs(verticalRect.top - horizontalRect.top) < 2
              && vertical.closest('.table-inner-lines-row') === horizontal.closest('.table-inner-lines-row');
            vertical.checked = false;
            vertical.dispatchEvent(new Event('input', {bubbles:true}));
            const verticalHidden = {
              data:table.dataset.tableInnerVerticalLines,
              collapse:table.style.borderCollapse,
              outerLeft:table.rows[0].cells[0].style.borderLeftWidth,
              innerLeft:table.rows[0].cells[1].style.borderLeftWidth,
              outerRight:table.rows[0].cells[table.rows[0].cells.length - 1].style.borderRightWidth,
              horizontal:table.rows[1].cells[0].style.borderTopWidth
            };
            horizontal.checked = false;
            horizontal.dispatchEvent(new Event('input', {bubbles:true}));
            const bothHidden = {
              vertical:table.dataset.tableInnerVerticalLines,
              horizontal:table.dataset.tableInnerHorizontalLines,
              innerLeft:table.rows[0].cells[1].style.borderLeftWidth,
              innerTop:table.rows[1].cells[0].style.borderTopWidth,
              outerBottom:table.rows[table.rows.length - 1].cells[0].style.borderBottomWidth
            };
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const restored = elements.preview.querySelector('table');
            activeInsertedComponent = restored;
            properties._sync();
            const restoredState = {
              vertical:document.querySelector('#tableInnerVerticalLines').checked,
              horizontal:document.querySelector('#tableInnerHorizontalLines').checked,
              innerLeft:restored.rows[0].cells[1].style.borderLeftWidth,
              innerTop:restored.rows[1].cells[0].style.borderTopWidth
            };
            restored.removeAttribute('data-table-inner-vertical-lines');
            restored.removeAttribute('data-table-inner-horizontal-lines');
            properties._sync();
            return {sameSettingsRow, verticalHidden, bothHidden, restored:restoredState,
              legacy:{vertical:vertical.checked, horizontal:horizontal.checked}};
        }""")
        self.assertTrue(result['sameSettingsRow'])
        self.assertEqual(result['verticalHidden'], {
            'data': 'false', 'collapse': 'separate', 'outerLeft': '1px',
            'innerLeft': '0px', 'outerRight': '1px', 'horizontal': '1px'})
        self.assertEqual(result['bothHidden'], {
            'vertical': 'false', 'horizontal': 'false', 'innerLeft': '0px',
            'innerTop': '0px', 'outerBottom': '1px'})
        self.assertEqual(result['restored'], {
            'vertical': False, 'horizontal': False, 'innerLeft': '0px', 'innerTop': '0px'})
        self.assertEqual(result['legacy'], {'vertical': True, 'horizontal': True})

    def test_table_border_color_is_customizable_and_survives_round_trip(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('table');
            const table = elements.preview.querySelector('table');
            activeInsertedComponent = table;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const cellColor = document.querySelector('#tableCellColor');
            const borderColor = document.querySelector('#tableBorderColor');
            const borderColorText = document.querySelector('#tableBorderColorText');
            const sameSettingsRow = cellColor.closest('.row') === borderColor.closest('.row');
            const hasPalette = Boolean(borderColor.closest('.color-row').querySelector('.swatch-palette'));
            borderColorText.value = '#123456';
            borderColorText.dispatchEvent(new Event('input', {bubbles:true}));
            const changed = {
              data:table.dataset.tableBorderColor,
              top:table.rows[0].cells[0].style.borderTopColor,
              inner:table.rows[1].cells[1].style.borderLeftColor
            };
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const restored = elements.preview.querySelector('table');
            activeInsertedComponent = restored;
            properties._sync();
            const roundTrip = {
              control:borderColorText.value,
              data:restored.dataset.tableBorderColor,
              top:restored.rows[0].cells[0].style.borderTopColor
            };
            restored.removeAttribute('data-table-border-color');
            restored.rows[0].cells[0].style.borderColor = '#654321';
            properties._sync();
            return {sameSettingsRow, hasPalette, changed, roundTrip, legacy:borderColorText.value};
        }""")
        self.assertTrue(result['sameSettingsRow'])
        self.assertTrue(result['hasPalette'])
        self.assertEqual(result['changed'], {
            'data': '#123456', 'top': 'rgb(18, 52, 86)', 'inner': 'rgb(18, 52, 86)'})
        self.assertEqual(result['roundTrip'], {
            'control': '#123456', 'data': '#123456', 'top': 'rgb(18, 52, 86)'})
        self.assertEqual(result['legacy'], '#654321')

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
            const headingA = makeHeading('見出しA');
            const headingB = makeHeading('見出しB');
            headingA.querySelector('[data-heading-content]').innerHTML = '見出し<span style="color:#c2410c">A</span> ';
            headingB.querySelector('[data-heading-content]').innerHTML = '見出し<span style="color:#2563eb"><strong>B</strong></span>';
            elements.preview.replaceChildren(toc, headingA, headingB);
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
              colors: links.map(link => link.style.color),
              headingDisplay: elements.preview.querySelector('[data-inserted-component="heading"] h2').style.display
            };
            const outputHolder = document.createElement('div');
            outputHolder.innerHTML = formatOutputHtml(getPersistablePreviewHtml());
            enabled.outputLinks = Array.from(outputHolder.querySelectorAll(`a[href="#${toc.id}"]`)).length;
            enabled.outputEditorMarkers = outputHolder.querySelectorAll('[data-toc-back-link]').length;
            enabled.outputColors = Array.from(outputHolder.querySelectorAll('[data-toc-back-link]')).map(link => link.style.color);

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
        self.assertEqual(result["enabled"]["colors"], ["rgb(194, 65, 12)", "rgb(37, 99, 235)"])
        self.assertEqual(result["enabled"]["headingDisplay"], "flex")
        self.assertEqual(result["enabled"]["outputLinks"], 2)
        self.assertEqual(result["enabled"]["outputEditorMarkers"], 2)
        self.assertEqual(result["enabled"]["outputColors"], ["rgb(194, 65, 12)", "rgb(37, 99, 235)"])
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

    def test_toc_heading_number_size_is_adjustable_and_backward_compatible(self):
        result = self.page.evaluate("""() => {
            elements.preview.innerHTML = insertedComponentHtml('toc') +
              '<div data-inserted-component="heading"><h2 id="heading-1" style="font-size:30px"><span data-heading-content>見出し</span></h2></div>';
            const toc = elements.preview.querySelector('[data-inserted-component="toc"]');
            refreshTocComponent(toc);
            toc.dataset.tocHeadingNumbers = 'true';
            activeInsertedComponent = toc;
            const properties = document.querySelector('.inserted-component-properties');
            properties._sync();
            const control = document.querySelector('#tocHeadingNumberSize');
            syncTocBackLinks();
            const initial = {
              control:control.value,
              inline:elements.preview.querySelector('[data-toc-heading-number]').style.fontSize
            };
            control.value = '22';
            control.dispatchEvent(new Event('input', {bubbles:true}));
            const adjusted = elements.preview.querySelector('[data-toc-heading-number]').style.fontSize;
            const html = formatOutputHtml(getPersistablePreviewHtml());
            importArticleHtml(html);
            const restoredToc = elements.preview.querySelector('[data-inserted-component="toc"]');
            const restoredNumber = elements.preview.querySelector('[data-toc-heading-number]');
            return {initial, adjusted, dataset:restoredToc.dataset.tocHeadingNumberSize,
              restored:restoredNumber.style.fontSize};
        }""")
        self.assertEqual(result['initial'], {'control': '', 'inline': ''})
        self.assertEqual(result['adjusted'], '22px')
        self.assertEqual(result['dataset'], '22')
        self.assertEqual(result['restored'], '22px')

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
