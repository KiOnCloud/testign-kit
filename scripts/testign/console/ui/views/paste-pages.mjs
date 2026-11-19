// Manual mode of Close: the pages to paste into the wiki by hand. testign wrote nothing.

import { h, icon } from '../dom.mjs';
import { askBody } from '../markdown.mjs';
import { banner } from './shell.mjs';

export function copyToClipboard(ctx, text) {
  const fail = () => ctx.toast(ctx.t('copy_failed'), 'danger');
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    navigator.clipboard.writeText(text).then(() => ctx.toast(ctx.t('copied')), fail);
  } else {
    fail();
  }
}

/** The pages of a `paste-pages` ask, each with its name, a copy button and the content as written. */
export function renderPastePages(ctx, ask) {
  const { t } = ctx;
  return h('div.stack-16', [
    banner('info', t('paste_title'), t('paste_body')),
    ask.body ? askBody(ask.body) : null,
    ...(ask.pages || []).map((page, i) => h('section.diff-box', { 'aria-label': page.name }, [
      h('div.diff-head', [
        icon('file', 'k-icon--sm'), h('code.k-mono.text-1.break', page.name),
        h('button.k-btn.k-btn--ghost.k-btn--sm.push-right', {
          type: 'button', dataset: { copyPage: String(i) }, on: { click: () => copyToClipboard(ctx, page.new_content) },
        }, [icon('copy'), t('copy')]),
      ]),
      h('pre.page-content', page.new_content),
    ])),
  ]);
}
