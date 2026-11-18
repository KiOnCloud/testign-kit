// Answers to the agent's asks. The builders are pure (the server checks every answer again);
// renderQuestions draws a `questions` ask as radio or checkbox groups with an optional "Other".

import { h, icon, mount } from '../dom.mjs';

const ROW_ACTIONS = ['write', 'skip', 'edit'];

/** Anchors typed as "a, b; c" (also 、 and ，) → ['a', 'b', 'c']. */
export function splitAnchors(text) {
  return String(text || '').split(/[,;、，\n]/).map((s) => s.trim()).filter(Boolean);
}

/**
 * `picks` holds one {selected: [labels], other: text} per question.
 * Returns {ok: true, answer} or {ok: false, missing: [question indexes]}.
 */
export function questionsAnswer(ask, picks) {
  const questions = (ask && ask.questions) || [];
  const missing = [];
  const answer = questions.map((q, i) => {
    const pick = (picks && picks[i]) || {};
    const labels = new Set((q.options || []).map((o) => o.label));
    let selected = (Array.isArray(pick.selected) ? pick.selected : []).filter((s) => labels.has(s));
    if (!q.multiSelect) selected = selected.slice(0, 1);
    let other = typeof pick.other === 'string' ? pick.other : '';
    if (q.other !== 'multiline') other = other.replace(/[\r\n]+/g, ' ');
    other = other.trim() ? other : '';
    if (!selected.length && !other) missing.push(i);
    return other ? { selected, other } : { selected };
  });
  return missing.length ? { ok: false, missing } : { ok: true, answer };
}

/**
 * `choices` maps row id → {action, decision?, anchors?, page?}. Every asked row needs an action;
 * an edit needs at least one field that differs from the row as asked.
 * Returns {ok: true, answer: {rows}} or {ok: false, missing: [row ids], badEdits: [row ids]}.
 */
export function reviewAnswer(ask, choices) {
  const rows = (ask && ask.rows) || [];
  const missing = [];
  const badEdits = [];
  const out = {};
  for (const row of rows) {
    const c = (choices && choices[row.row]) || {};
    if (!ROW_ACTIONS.includes(c.action)) {
      missing.push(row.row);
      continue;
    }
    if (c.action !== 'edit') {
      out[row.row] = { action: c.action };
      continue;
    }
    const item = { action: 'edit' };
    if (typeof c.decision === 'string' && c.decision.trim() && c.decision.trim() !== String(row.decision || '').trim()) {
      item.decision = c.decision.trim();
    }
    if (Array.isArray(c.anchors)) {
      const anchors = c.anchors.map((a) => String(a).trim()).filter(Boolean);
      if (JSON.stringify(anchors) !== JSON.stringify(row.anchors || [])) item.anchors = anchors;
    }
    if (typeof c.page === 'string' && c.page.trim() && c.page.trim() !== String(row.page || '').trim()) {
      item.page = c.page.trim();
    }
    if (Object.keys(item).length === 1) badEdits.push(row.row);
    else out[row.row] = item;
  }
  if (missing.length || badEdits.length) return { ok: false, missing, badEdits };
  return { ok: true, answer: { rows: out } };
}

export function confirmAnswer(confirm) {
  return { confirm: confirm === true };
}

export function pasteAnswer() {
  return { done: true };
}

/**
 * A `questions` ask as a form. `onSubmit(answer)` returns a promise; while it runs the form is
 * disabled. The primary button is the view's one accent.
 */
export function renderQuestions({ t, ask, lang, onSubmit, onCancel }) {
  const picks = (ask.questions || []).map(() => ({ selected: [], other: '' }));
  const errorBox = h('div', { role: 'alert' });
  const groups = (ask.questions || []).map((q, qi) => {
    const name = `q-${ask.id}-${qi}`;
    const type = q.multiSelect ? 'checkbox' : 'radio';
    const options = (q.options || []).map((o, oi) => {
      const input = h('input', { type, name, value: o.label, id: `${name}-${oi}` });
      input.addEventListener('change', () => {
        if (q.multiSelect) {
          picks[qi].selected = input.checked
            ? [...picks[qi].selected, o.label]
            : picks[qi].selected.filter((s) => s !== o.label);
        } else if (input.checked) {
          picks[qi].selected = [o.label];
        }
      });
      return h(`label.${q.multiSelect ? 'k-check' : 'k-radio'}.ask-option`, { for: `${name}-${oi}` }, [
        input,
        q.multiSelect ? h('span.k-check__box', icon('check')) : h('span.k-radio__dot'),
        h('span.stack-2', [h('span.ask-label', { lang }, o.label),
          o.description ? h('span.k-note.text-2', { lang }, o.description) : null]),
      ]);
    });
    const otherAttrs = { id: `${name}-other`, placeholder: t('ask_other_ph') };
    const other = q.other === 'multiline'
      ? h('textarea.k-textarea', { ...otherAttrs, rows: '3' })
      : h('input.k-input', { ...otherAttrs, type: 'text' });
    other.addEventListener('input', () => { picks[qi].other = other.value; });
    return h('fieldset.ask-group', [
      h('legend.ask-question', [q.header ? h('span.k-badge.k-badge--outline', { lang }, q.header) : null, ' ',
        h('span', { lang }, q.question)]),
      h('div.stack-8', { role: q.multiSelect ? 'group' : 'radiogroup', 'aria-label': q.question }, options),
      h('label.k-field', { for: `${name}-other` }, [
        h('span.k-field__label', [t('ask_other'), ' ', h('span.k-muted.ws-sub', t('ask_optional'))]), other]),
    ]);
  });
  const send = h('button.k-btn.k-btn--primary', { type: 'submit' }, [t('ask_send'),
    h('span.k-kbd-group', [h('kbd.k-kbd.k-kbd--on-accent', 'Ctrl'), h('kbd.k-kbd.k-kbd--on-accent', '↵')])]);
  const form = h('form.ask-form', { 'aria-label': t('ask_title') }, [
    h('div.stack-4', [h('span.k-section-label', t('ask_title')), ask.body ? h('p.ask-body', { lang }, ask.body) : null]),
    ...groups,
    errorBox,
    h('div.ask-actions', [
      h('span.k-note.push-right-auto', t('ask_only_this_job')),
      onCancel ? h('button.k-btn.k-btn--ghost', { type: 'button', on: { click: onCancel } }, t('job_release')) : null,
      send,
    ]),
  ]);
  const submit = async (event) => {
    if (event) event.preventDefault();
    const result = questionsAnswer(ask, picks);
    if (!result.ok) {
      mount(errorBox, h('p.k-field__error', [icon('warning'),
        t('ask_err_missing', { n: result.missing.map((i) => i + 1).join(', ') })]));
      return;
    }
    mount(errorBox);
    send.disabled = true;
    try {
      await onSubmit(result.answer);
    } catch (err) {
      mount(errorBox, h('p.k-field__error', [icon('warning'), err && err.userText ? err.userText : String(err && err.message || err)]));
    } finally {
      send.disabled = false;
    }
  };
  form.addEventListener('submit', submit);
  form.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) submit(event);
  });
  return form;
}
