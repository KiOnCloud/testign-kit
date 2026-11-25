// The sign-in card a run shows while its job waits for the tester to sign in. The tester signs in
// by hand in their own Chrome; no screen takes or stores an account value.

import { h, icon, mount } from '../dom.mjs';
import { NONE } from '../format.mjs';
import { hostOf } from '../hosts.mjs';
import { jobErrorText, tooNewNotice } from './job-actions.mjs';

/** An http(s) URL whose host reads the same in every parser as a link in a new tab; anything else as text. */
export function urlLink(url) {
  if (!url) return h('span.yh-muted', NONE);
  if (hostOf(url) === null) return h('code.mono.break', url);
  return h('a.lnk.break', { href: url, target: '_blank', rel: 'noopener noreferrer' }, [h('code.mono', url), ' ', icon('external', 'k-icon--sm')]);
}

/** The sign-in card for a webtest-run job whose ask is `sign-in` (the full job record). */
export function signInCard(ctx, job) {
  const { t } = ctx;
  const ask = job.ask;
  const list = ask.checklist || {};
  const prev = ask.previous;
  const title = h('div.panel-head', [icon('key'), h('h2.yh-h3.m-0', { id: `signin-${ask.id}` },
    t('login_ask_title', { label: list.label || ask.scenario }))]);
  if (job.can_answer === false) {
    return h('section.panel.signin-card', { 'aria-labelledby': `signin-${ask.id}`, dataset: { signInCard: ask.id } }, [title, tooNewNotice(t)]);
  }
  const errorBox = h('div', { role: 'alert' });
  const send = async (choice, button) => {
    button.disabled = true;
    try {
      await ctx.api.answer(job.id, ask.id, { choice });
      ctx.toast(t('ask_sent'));
      ctx.invalidate(`job:${job.id}`);
      ctx.pollNow();
    } catch (err) {
      button.disabled = false;
      if (err && err.status === 409) ctx.pollNow();
      mount(errorBox, h('p.k-field__error', [icon('warning'), jobErrorText(t, err)]));
    }
  };
  const signedIn = h('button.yh-btn.yh-btn--primary', { type: 'button', dataset: { signIn: 'signed-in' } }, t('login_signed_in'));
  const skip = h('button.yh-btn.yh-btn--ghost', { type: 'button', dataset: { signIn: 'skip' } }, t('login_skip'));
  signedIn.addEventListener('click', () => send('signed-in', signedIn));
  skip.addEventListener('click', () => send('skip', skip));
  const steps = [];
  if (prev) {
    steps.push(h('li', [t('login_sign_out_of', { label: prev.label || prev.name }), ' ', urlLink(prev.signout_url)]));
  }
  if (list.login_url) steps.push(h('li', [t('login_open_signin'), ' ', urlLink(list.login_url)]));
  for (const s of list.steps || []) steps.push(h('li', s));
  const check = list.signed_in_check || {};
  return h('section.panel.signin-card', { 'aria-labelledby': `signin-${ask.id}`, dataset: { signInCard: ask.id } }, [
    title,
    h('p.m-0', prev ? t('login_ask_switch', { from: prev.label || prev.name, to: list.label || ask.scenario }) : t('login_ask_body')),
    h('ol.signin-steps', steps),
    list.account_hint ? h('p.k-note', [h('strong', t('login_hint')), ' ', list.account_hint]) : null,
    check.text || check.url ? h('p.k-note', [h('strong', t('login_check')), ' ', check.text || '', check.url ? [' · ', urlLink(check.url)] : null]) : null,
    h('p.k-note', t('login_no_values')),
    errorBox,
    h('div.foot', [signedIn, skip, h('span.k-note', t('login_skip_note'))]),
  ]);
}
