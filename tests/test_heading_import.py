"""Heading/TOC round trips, including exports without editor metadata."""
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright


class HeadingImportTests(unittest.TestCase):
    def test_legacy_and_current_exports_remain_editable(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page()
            page.route('https://**/*', lambda route: route.abort())
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto((Path(__file__).resolve().parents[1] / 'index.html').as_uri())
            for legacy in (True, False):
                result = page.evaluate('''legacy => {
                  const holder = document.createElement('div');
                  holder.innerHTML = insertedComponentHtml('toc') + `
                    <div data-inserted-component="body" style="line-height:1.9">
                      Before
                      <div data-inserted-component="heading"><h2 id="heading-1">
                        <span data-heading-prefix aria-hidden="true">★ </span>
                        <span data-heading-content><b>Title</b><br>Second line</span>
                      </h2></div>
                      After
                    </div>`;
                  const body = holder.querySelector('[data-inserted-component="body"]');
                  writeDocumentBlockSettings(body, {...readDocumentBlockSettings('body'), includeCard:false});
                  elements.preview.replaceChildren(...holder.childNodes);
                  ensureDocumentBlocks();
                  const toc = elements.preview.querySelector('nav');
                  toc.dataset.tocBackLinks = 'true';
                  toc.dataset.tocHeadingNumbers = 'true';
                  refreshTocComponent(toc);
                  let html = formatOutputHtml(getPersistablePreviewHtml());
                  if (legacy) {
                    holder.innerHTML = html;
                    for (const attr of ['data-pl-settings', 'data-heading-content',
                        'data-heading-prefix', 'data-toc-back-link', 'data-toc-back-layout']) {
                      holder.querySelectorAll(`[${attr}]`).forEach(el => el.removeAttribute(attr));
                    }
                  }
                  else holder.innerHTML = html;
                  // A browser editing artifact outside the title is invisible
                  // in the flex heading, but must not be moved into its text.
                  holder.querySelector('h2').prepend(document.createElement('br'));
                  html = holder.innerHTML;
                  // Import must not depend on the current settings-panel mode.
                  elements.includeCard.checked = true;
                  const states = [];
                  for (let i = 0; i < 3; i++) {
                    importArticleHtml(html);
                    const heading = elements.preview.querySelector('h2');
                    const content = heading.querySelector('[data-heading-content]');
                    content.querySelector('b').textContent = 'Edited';
                    content.dispatchEvent(new Event('input', {bubbles:true}));
                    capturePreviewEdits();
                    states.push({
                      invalid:findInvalidNestedStructure()?.message || null,
                      links:heading.querySelectorAll('a[href="#p-player-toc"]').length,
                      nestedLinks:content.querySelectorAll('a').length,
                      title:content.textContent.replace(/\\s+/g, ' ').trim(),
                      prefix:heading.querySelector('[data-heading-prefix]').textContent.trim(),
                      numbers:heading.querySelectorAll('[data-toc-heading-number]').length,
                      breaks:content.querySelectorAll('br').length,
                      leadingBreak:content.firstElementChild?.tagName === 'BR',
                      plain:!isBodyCard(elements.preview.querySelector('[data-inserted-component="body"]'))
                    });
                    html = formatOutputHtml(getPersistablePreviewHtml());
                  }
                  elements.preview.querySelector('nav').dataset.tocBackLinks = 'false';
                  capturePreviewEdits();
                  return {states, disabled:elements.preview.querySelectorAll('h2 a').length};
                }''', legacy)
                for state in result['states']:
                    self.assertEqual(state, dict(invalid=None, links=1, nestedLinks=0,
                                                title='Edited Second line', prefix='★', numbers=1,
                                                breaks=1, leadingBreak=False, plain=True))
                self.assertEqual(result['disabled'], 0)
            self.assertEqual(errors, [])
            browser.close()


if __name__ == '__main__':
    unittest.main()
