// A small Markdown subset rendered as elements: paragraphs, ### headings, bullet and numbered lists,
// pipe tables and the inline marks `inline` knows. Everything is built with `h`, so text stays text:
// no markup from a report or an agent is ever parsed as HTML.

import { h, inline } from './dom.mjs';

const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const SEPARATOR_CELL = /^:?-{2,}:?$/;

/** The cells of one pipe-table line: split on unescaped `|`, `\|` kept as `|`, cells trimmed. */
export function pipeCells(line) {
  let text = String(line).trim();
  if (text.startsWith('|')) text = text.slice(1);
  if (text.endsWith('|') && !text.endsWith('\\|')) text = text.slice(0, -1);
  return text.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
}

/** Paragraphs, headings and lists from lines; table lines are skipped (callers render tables apart). */
export function prose(lines, lang) {
  return blocks(lines, lang, false);
}

/** A table from `{header, rows}`, in the report's table style, scrolling sideways when wide. */
export function markdownTable(table, lang) {
  return h('div.k-table-wrap.table-box', h('div.scroll-x', h('table.k-table.report-table', [
    h('thead', h('tr', table.header.map((x) => h('th', { lang }, x)))),
    h('tbody', table.rows.map((cells) => h('tr', cells.map((c) => h('td', { lang }, inline(c)))))),
  ])));
}

/** Free Markdown text (an agent's ask body) as blocks, tables included. */
export function markdownBlocks(text, lang) {
  return blocks(String(text).split(/\r?\n/), lang, true);
}

/** The body of an agent's ask, rendered as Markdown. */
export function askBody(body, lang) {
  return h('div.ask-body', { lang }, markdownBlocks(body, lang));
}

function blocks(lines, lang, withTables) {
  const out = [];
  let list = null;
  let listTag = null;
  let table = null;
  const flushList = () => { if (list) { out.push(h(listTag, { class: 'prose-list', lang }, list)); list = null; listTag = null; } };
  const flushTable = () => { if (table) { out.push(markdownTable(table, lang)); table = null; } };
  for (const raw of lines) {
    const line = String(raw).trimEnd();
    const trimmed = line.trim();
    if (trimmed.startsWith('|')) {
      flushList();
      if (!withTables) continue;
      const cells = pipeCells(trimmed);
      if (!table) table = { header: cells, rows: [] };
      else if (!cells.every((c) => !c || SEPARATOR_CELL.test(c))) table.rows.push(cells);
      continue;
    }
    flushTable();
    if (!trimmed || trimmed === '---') { flushList(); continue; }
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      const tag = bullet ? 'ul' : 'ol';
      if (listTag !== tag) { flushList(); list = []; listTag = tag; }
      list.push(h('li', inline((bullet || numbered)[1])));
      continue;
    }
    flushList();
    if (/^#{3,6}\s/.test(line)) out.push(h('h3.prose-heading', { lang }, inline(line.replace(/^#+\s*/, ''))));
    else out.push(h('p.prose-p', { lang }, inline(line)));
  }
  flushList();
  flushTable();
  return out;
}
