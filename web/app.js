// Britannica-Wiki Lens. Reads the JSON that `nemotron-challenge run site` writes to data/.
// Routes: #viewer?p=<row_index>&e=<entry_id>  #reading  #match?e=<entry_id>  #analytics  #agent?r=<run_id>  #pipeline

const $view = document.getElementById('view');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const pct = n => `${Math.round(n * 100)}%`;
const fmt = (n, d = 2) => (n == null ? '–' : Number(n).toFixed(d));
let D; // { pages, drift, runs }

// Lucide icon paths (24x24, stroke). Decorative unless a label is given.
const ICONS = {
  warn: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  up: '<path d="m18 15-6-6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  ext: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  minus: '<path d="M5 12h14"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
  dot: '<circle cx="12" cy="12" r="4"/>',
};
const icon = (n, cls = 'h-4 w-4') => `<svg class="${cls} inline-block shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;

// ---------- Data helpers ----------
const allEntries = () => D.pages.flatMap(p => p.entries.map(e => ({ ...e, page: p })));
const findEntry = id => allEntries().find(e => e.entry_id === id);
const entryByCrop = path => allEntries().find(e => e.crop_path === path);
const cropUrl = e => `crops/${e.crop_path.split('/').pop()}`;
const label = e => e.headword || (e.kind === 'plate' ? 'Plate' : e.kind === 'continuation' ? 'Continuation' : e.entry_id);
const lowQ = e => e.quality?.low_quality === true;
const pageAspect = p => `aspect-ratio:${p.width} / ${p.height}`;
const bboxStyle = (p, [x0, y0, x1, y1]) =>
  `left:${(x0 / p.width) * 100}%;top:${(y0 / p.height) * 100}%;width:${((x1 - x0) / p.width) * 100}%;height:${((y1 - y0) / p.height) * 100}%`;
const boxKind = e => (e.kind === 'plate' ? 'illustration' : 'heading');
const wikiUrl = (pageId, revisionId) => {
  for (const e of allEntries()) {
    const c = e.match?.candidates.find(c => c.page_id === pageId);
    if (c) return c.url;
  }
  return revisionId ? `https://en.wikipedia.org/w/index.php?oldid=${revisionId}` : `https://en.wikipedia.org/?curid=${pageId}`;
};

const chip = (cls, html, href) => {
  const ext = href?.startsWith('http');
  return `<a ${href ? `href="${esc(href)}"` : ''} ${ext ? 'target="_blank" rel="noopener"' : ''}
     class="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[13px] font-bold transition-colors ${cls}">${html}${ext ? icon('ext', 'h-3 w-3') : ''}</a>`;
};
const britChip = (entryId, text) => {
  const e = findEntry(entryId);
  return chip('bg-brit-soft text-brit hover:bg-brit hover:text-white', `Britannica · ${esc(text ?? (e ? label(e) : entryId))}`,
    e ? `#viewer?p=${e.page.row_index}&e=${e.entry_id}` : null);
};
const wikiChip = (pageId, revisionId, text) =>
  chip('bg-wiki-soft text-wiki hover:bg-wiki hover:text-white', `Wikipedia · ${esc(text ?? `${pageId}@${revisionId}`)}`, wikiUrl(pageId, revisionId));

const card = (title, body, extra = '') =>
  `<section class="rise rounded-xl border border-line bg-card p-5 shadow-sm ${extra}">
     <h2 class="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-sub">${title}</h2>${body}</section>`;
const stat = (name, value, cls = 'text-fg') =>
  `<div class="rounded-lg border border-line bg-card px-4 py-2"><div class="text-[11px] uppercase tracking-wider text-sub">${name}</div><div class="text-lg font-bold ${cls}">${value}</div></div>`;
const btn = (active, activeCls = 'bg-wiki text-white') =>
  `cursor-pointer rounded-md px-3 py-1.5 text-sm transition-colors ${active ? activeCls : 'bg-muted text-fg hover:bg-line'}`;
const empty = msg => `<p class="rounded-xl border border-dashed border-line bg-card p-8 text-center text-sub">${msg}</p>`;

// ---------- 1. Archive Viewer ----------
function texSource(page) {
  // ponytail: escapes the LaTeX specials only; the compiled PDF comes from the extract stage.
  const t = s => String(s ?? '').replace(/([%&_#$])/g, '\\$1').replace(/ſ/g, 's');
  return `\\documentclass[twocolumn]{article}\n\\begin{document}\n` +
    page.entries.map(e => e.kind === 'plate'
      ? `\\begin{figure}\\caption{${t(e.text)}}\\end{figure}`
      : `\\section*{${t(label(e))}}\n${t(e.text)}`).join('\n\n') + `\n\\end{document}`;
}

const entryParagraph = e => {
  if (e.kind === 'plate')
    return `<figure class="my-2 flex items-center justify-center gap-2 border-y border-[#e5dcc7] py-3 text-sm italic text-sub">${icon('image')} ${esc(e.text)}</figure>`;
  const h = e.headword && e.text.toUpperCase().startsWith(e.headword.toUpperCase()) ? e.headword.length : 0;
  return `<p class="text-justify text-[17px] leading-snug ${e.kind === 'continuation' ? 'italic text-sub' : ''}">` +
    (h ? `<span class="font-bold tracking-wider">${esc(e.text.slice(0, h))}</span>${esc(e.text.slice(h))}` : esc(e.text)) + `</p>`;
};

function viewer(q) {
  if (!D.pages.length) return ($view.innerHTML = empty('No extracted pages yet. Run <code>nemotron-challenge run extract</code> and <code>run site</code>.'));
  const page = D.pages.find(p => String(p.row_index) === q.get('p')) || D.pages[0];
  const sel = q.get('e');
  const raw = q.get('raw') === '1';
  const zoom = +(q.get('z') || 1);
  const link = o => '#viewer?' + new URLSearchParams({ p: page.row_index, ...(sel && { e: sel }), ...(raw && { raw: 1 }), z: zoom, ...o });
  const heads = page.entries.filter(e => e.kind === 'entry').length;
  const warns = page.entries.filter(lowQ).length;

  const boxes = page.entries.flatMap(e => e.blocks.filter(b => b.page_id === page.page_id).map(b => `
    <a href="${link({ e: e.entry_id })}" aria-label="${esc(label(e))}${lowQ(e) ? ', low OCR quality' : ''}"
      class="box ${boxKind(e)} ${lowQ(e) ? 'warn' : ''} ${e.entry_id === sel ? 'active' : ''}" style="${bboxStyle(page, b.bbox)}">
      <span class="absolute -top-6 left-0 inline-flex items-center gap-1 whitespace-nowrap rounded bg-fg/85 px-1.5 py-0.5 text-[11px] text-white">
        ${lowQ(e) ? icon('warn', 'h-3 w-3 text-amber-300') : ''}${esc(label(e))}</span>
      <span class="ocr block h-full overflow-hidden p-1.5 font-serif text-[11px] leading-tight text-fg/70">${esc(b.text)}</span></a>`)).join('');

  const rendered = page.entries.map(e => `
    <a href="${link({ e: e.entry_id })}" class="mb-4 block break-inside-avoid rounded ${e.entry_id === sel ? '-mx-2 bg-brit-soft px-2 ring-1 ring-brit' : 'hover:bg-[#f3ead7]'}">
      ${entryParagraph(e)}
      ${lowQ(e) ? `<span class="mt-1 flex items-center gap-1 font-sans text-xs text-brit">${icon('warn', 'h-3 w-3')} Low OCR quality (suspect tokens ${pct(e.quality.ocr_suspect_ratio ?? 0)})</span>` : ''}
    </a>`).join('');

  const selected = page.entries.find(e => e.entry_id === sel);
  $view.innerHTML = `
    <div class="mb-5 flex flex-wrap items-end gap-3">
      <div>
        <p class="mb-1 text-xs uppercase tracking-wider text-sub">Scan (manifest row)</p>
        <div class="flex flex-wrap gap-1">${D.pages.map(p => `<a href="#viewer?p=${p.row_index}" class="${btn(p === page)}">${p.row_index}${p.status !== 'ok' ? ` · ${esc(p.status)}` : ''}</a>`).join('')}</div>
      </div>
      <div class="ml-auto flex flex-wrap gap-2">
        ${stat('Entries', heads)}
        ${stat('Parse 3.5 latency', page.parse ? `${(page.parse.latency_ms / 1000).toFixed(2)} s` : '–')}
        ${stat('Status', esc(page.status), page.status === 'ok' ? 'text-ok' : 'text-brit')}
        ${stat('Low-quality entries', warns, warns ? 'text-brit' : 'text-ok')}
      </div>
    </div>
    <div class="grid gap-5 lg:grid-cols-2">
      ${card(`<span class="h-2 w-2 rounded-full bg-brit"></span>Scan · volume ${esc(page.volume_id)}, row ${page.row_index}
        <span class="ml-auto flex items-center gap-1 normal-case tracking-normal">
          <a href="${link({ z: Math.max(1, zoom - 0.25) })}" aria-label="Zoom out" class="rounded p-1.5 hover:bg-muted">${icon('minus')}</a>
          <span class="w-10 text-center">${pct(zoom)}</span>
          <a href="${link({ z: Math.min(2.5, zoom + 0.25) })}" aria-label="Zoom in" class="rounded p-1.5 hover:bg-muted">${icon('plus')}</a></span>`,
        `<div class="max-h-[74vh] overflow-auto rounded-lg bg-muted p-3"><div class="mx-auto" style="width:min(${zoom * 100}%, ${zoom * 50}vh)">
           <div class="page relative rounded ${page.image_url ? '' : 'noscan'}" style="${pageAspect(page)}">
             ${page.image_url ? `<img src="${esc(page.image_url)}" alt="Scan ${esc(page.filename)}" class="absolute inset-0 h-full w-full rounded object-cover" onerror="this.parentNode.classList.add('noscan'); this.remove()">` : ''}
             ${boxes}
           </div></div></div>
         <ul class="mt-3 flex flex-wrap gap-4 text-xs text-sub">
           <li class="flex items-center gap-1.5"><span class="h-3 w-3 border-2 border-wiki"></span>Entry</li>
           <li class="flex items-center gap-1.5"><span class="h-3 w-3 border-2 border-tool"></span>Plate</li>
           <li class="flex items-center gap-1.5"><span class="h-3 w-3 border-2 border-dashed border-brit"></span>Low OCR quality</li></ul>
         <dl class="mt-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-line pt-3 text-xs">
           <dt class="text-sub">Page ID</dt><dd class="break-all font-mono">${esc(page.page_id)}</dd>
           <dt class="text-sub">Parse model</dt><dd class="font-mono">${esc(page.parse?.model ?? '–')}</dd>
           ${selected ? `<dt class="text-sub">Selected</dt><dd>${esc(selected.entry_id)} · ${esc(selected.kind)}
             ${selected.match ? `· <a class="font-bold text-wiki underline-offset-2 hover:underline" href="#match?e=${selected.entry_id}">See match →</a>` : ''}</dd>` : ''}
         </dl>`)}
      ${card(`<span class="h-2 w-2 rounded-full bg-wiki"></span>${page.latex_pdf_url && !raw ? 'Compiled LaTeX (PDF)' : raw ? 'LaTeX source' : 'Extracted text · LaTeX layout'}
        <a href="${link({ raw: raw ? 0 : 1 })}" class="ml-auto rounded-md border border-line px-2.5 py-1 normal-case tracking-normal text-wiki hover:bg-muted">${raw ? 'Rendered view' : 'Raw source'}</a>`,
        page.latex_pdf_url && !raw
          ? `<iframe src="${esc(page.latex_pdf_url)}" title="Compiled LaTeX PDF" class="h-[74vh] w-full rounded-lg border border-line"></iframe>`
          : raw
          ? `<pre class="max-h-[74vh] overflow-auto whitespace-pre-wrap rounded-lg bg-fg p-4 text-xs leading-relaxed text-emerald-300">${esc(texSource(page))}</pre>`
          : `<div class="latex max-h-[74vh] overflow-auto rounded-lg border border-[#e5dcc7] bg-[#FBF7EE] p-8 font-serif text-fg">
               <p class="mb-4 border-b border-[#e5dcc7] pb-2 text-center text-xs uppercase tracking-[0.3em] text-sub" style="column-span:all">Encyclopædia Britannica · volume ${esc(page.volume_id)}</p>${rendered}</div>`)}
    </div>`;
}

// ---------- 2. Match Explorer ----------
// Britannica entry is the query. Stages: BM25 (shared API) → Embed VL cosine → Rerank VL → decision rule.
function match(q) {
  const entries = allEntries().filter(e => e.match);
  if (!entries.length) return ($view.innerHTML = empty('No match records yet. Run <code>nemotron-challenge run match</code> and <code>run site</code>.'));
  const e = entries.find(x => x.entry_id === q.get('e')) || entries[0];
  const m = e.match;
  const by = key => m.candidates.filter(c => c[key] != null).sort((a, b) => a[key] - b[key]);
  const bm25 = by('bm25_rank'), embed = by('embed_rank'), rerank = by('rerank_rank');
  const maxBm25 = Math.max(...bm25.map(c => c.bm25_score), 1e-9);
  const logits = rerank.map(c => c.rerank_logit);
  const [lo, hi] = [Math.min(...logits), Math.max(...logits)];
  const norm = v => (hi > lo ? (v - lo) / (hi - lo) : 1);
  const bar = (v, color) => `<div class="mt-1.5 h-2 rounded-full bg-muted"><div class="h-2 rounded-full ${color}" style="width:${pct(Math.max(0, Math.min(1, v)))}"></div></div>`;
  const step = (n, text) => `<span class="flex h-6 w-6 items-center justify-center rounded-full bg-fg text-[11px] text-white">${n}</span>${text}`;
  const move = (from, to) => {
    if (from == null || to == null) return '';
    const d = from - to;
    return d > 0 ? `<span class="inline-flex items-center text-xs font-bold text-ok" aria-label="up ${d}">${icon('up', 'h-3 w-3')}${d}</span>`
      : d < 0 ? `<span class="inline-flex items-center text-xs font-bold text-bad" aria-label="down ${-d}">${icon('down', 'h-3 w-3')}${-d}</span>`
      : `<span class="text-xs text-sub">±0</span>`;
  };
  const isMatch = c => m.matched_wiki && c.page_id === m.matched_wiki.page_id;
  const statusCls = { matched: 'bg-ok-soft text-ok', rejected: 'bg-bad-soft text-bad', no_candidates: 'bg-muted text-sub', skipped: 'bg-muted text-sub' }[m.status];

  $view.innerHTML = `
    <div class="mb-5 flex flex-wrap items-end gap-3">
      <label class="text-xs uppercase tracking-wider text-sub">Britannica entry (query)
        <select onchange="location.hash='#match?e='+this.value" class="mt-1 block cursor-pointer rounded-md border border-line bg-card px-3 py-2 text-sm normal-case tracking-normal text-fg">
          ${entries.map(x => `<option value="${x.entry_id}" ${x === e ? 'selected' : ''}>${esc(label(x))} · ${esc(x.match.status)} · row ${x.page.row_index}</option>`).join('')}
        </select></label>
      <p class="ml-auto max-w-xl text-sm text-sub">Britannica → Wikipedia. The shared API returns BM25 keyword hits; Embed VL scores them against the entry text and page crop;
        Rerank VL orders the shortlist. Rerank scores are raw logits: they rank relevance, they do not prove factual agreement.</p>
    </div>
    <div class="grid gap-5 lg:grid-cols-2 2xl:grid-cols-4">
      ${card(step('A', 'Britannica entry'), `
        <h3 class="font-serif text-3xl font-semibold text-brit">${esc(label(e))}</h3>
        <p class="mt-1 text-xs text-sub">${esc(e.entry_id)} · volume ${esc(e.page.volume_id)}, row ${e.page.row_index}${lowQ(e) ? ' · <span class="text-brit">low OCR quality</span>' : ''}</p>
        <div class="mt-4 flex gap-4">
          <div class="page relative w-24 shrink-0 overflow-hidden rounded" style="${pageAspect(e.page)}" title="Entry crop sent to Embed VL">
            <img src="${esc(cropUrl(e))}" alt="" class="absolute inset-0 h-full w-full object-contain" onerror="this.remove()">
            ${e.blocks.filter(b => b.page_id === e.page.page_id).map(b => `<div class="box ${boxKind(e)} active" style="${bboxStyle(e.page, b.bbox)}"></div>`).join('')}
          </div>
          <blockquote class="max-h-48 overflow-auto border-l-2 border-brit pl-3 font-serif text-[16px] italic leading-snug">“${esc(e.text)}”</blockquote>
        </div>
        ${m.queries?.length ? `<p class="mt-4 text-[11px] font-bold uppercase tracking-wider text-sub">BM25 queries (pooled)</p>
          ${m.queries.map(x => `<code class="mt-1 block rounded-md bg-muted p-2 text-xs">${esc(x)}</code>`).join('')}` : ''}
        <a href="#viewer?p=${e.page.row_index}&e=${e.entry_id}" class="mt-4 inline-block text-sm font-bold text-brit underline-offset-2 hover:underline">Open in Archive Viewer →</a>`)}
      ${card(step('B', `Wikipedia API · BM25 · top ${Math.min(6, bm25.length)} of ${bm25.length}`), bm25.length ? bm25.slice(0, 6).map(c => {
        const dropped = c.embed_rank == null;
        return `<div class="mb-3.5 ${dropped ? 'opacity-60' : ''}"><div class="flex justify-between gap-2 text-sm"><span><span class="text-sub">#${c.bm25_rank}</span> ${esc(c.title)}</span><span class="tabular-nums text-sub">${fmt(c.bm25_score, 1)}</span></div>
          ${bar(c.bm25_score / maxBm25, 'bg-sub/40')}${dropped ? `<p class="mt-1 text-xs text-bad">Keyword hit, not scored by Embed VL</p>` : ''}</div>`;
      }).join('') : `<p class="text-sm text-sub">No BM25 candidates.</p>`)}
      ${card(step('C', `Embed VL · cosine · top ${Math.min(5, embed.length)} of ${embed.length}`), embed.length ? embed.slice(0, 5).map(c => `
        <div class="mb-3.5"><div class="flex items-center justify-between gap-2 text-sm"><span><span class="text-sub">#${c.bm25_rank}→#${c.embed_rank}</span> ${esc(c.title)} ${move(c.bm25_rank, c.embed_rank)}</span><span class="tabular-nums text-sub">${fmt(c.embed_cosine)}</span></div>
        ${bar(c.embed_cosine, 'bg-wiki/60')}</div>`).join('') : `<p class="text-sm text-sub">Not scored.</p>`)}
      ${card(step('D', 'Rerank VL · raw logit'), (rerank.length ? rerank.map(c => `
        <div class="mb-3 ${isMatch(c) ? '-mx-2 rounded-lg bg-ok-soft p-2' : ''}">
          <div class="flex items-center justify-between gap-2 text-sm">
            <span><span class="text-sub">#${c.embed_rank ?? '–'}→#${c.rerank_rank}</span> ${isMatch(c) ? '<b>' : ''}${esc(c.title)}${isMatch(c) ? '</b>' : ''} ${move(c.embed_rank, c.rerank_rank)}</span>
            <span class="tabular-nums text-sub">${fmt(c.rerank_logit)}</span></div>
          ${bar(norm(c.rerank_logit), isMatch(c) ? 'bg-ok' : 'bg-sub/40')}</div>`).join('') : `<p class="text-sm text-sub">Not reranked.</p>`) + `
        <div class="mt-4 space-y-2 border-t border-line pt-4 text-sm">
          <div class="flex flex-wrap items-center gap-2">
            <span class="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[13px] font-bold ${statusCls}">${icon(m.status === 'matched' ? 'check' : 'ban', 'h-3.5 w-3.5')} ${esc(m.status.replace('_', ' '))}</span>
            ${m.matched_wiki ? chip('bg-wiki text-white hover:bg-wiki/90', esc(m.matched_wiki.title), m.matched_wiki.url) : ''}
          </div>
          <p class="text-xs text-sub">${esc(m.reason)}${m.rerank_margin != null ? ` · margin ${fmt(m.rerank_margin)}` : ''}</p>
          <p class="font-mono text-[11px] text-sub">${esc(m.method_version)}</p>
        </div>`)}
    </div>`;
}

// ---------- 3. Analytics ----------
function analytics() {
  const d = D.drift;
  if (!d.terms.length) return ($view.innerHTML = empty('No comparison results yet. Run <code>nemotron-challenge run compare</code> and <code>run site</code>.'));
  const terms = [...d.terms].sort((a, b) => b.log_ratio - a.log_ratio);
  const max = Math.max(...terms.map(t => Math.abs(t.log_ratio)), 1e-9);
  const bars = terms.map(t => {
    const brit = t.log_ratio > 0;
    return `<div class="relative h-8" title="${esc(t.term)}: Britannica ${t.brit_per_10k} vs Wikipedia ${t.wiki_per_10k} per 10k tokens">
      <div class="absolute top-1.5 h-5 rounded ${brit ? 'bg-brit' : 'bg-wiki'}" style="${brit ? 'right' : 'left'}:50%;width:${(Math.abs(t.log_ratio) / max) * 48}%"></div>
      <span class="absolute top-1.5 text-sm ${brit ? 'left-1/2 pl-2' : 'right-1/2 pr-2 text-right'}">
        <span class="font-serif text-base italic">${esc(t.term)}</span> <span class="text-xs tabular-nums text-sub">${fmt(t.brit_per_10k, 1)} / ${fmt(t.wiki_per_10k, 1)}</span></span></div>`;
  }).join('');
  const quotes = [...d.terms].sort((a, b) => Math.abs(b.log_ratio) - Math.abs(a.log_ratio)).slice(0, 4);

  $view.innerHTML = `<div class="grid gap-5 lg:grid-cols-3">
    ${card('Word frequency shift · log₂ ratio of rates per 10k tokens', `
      <div class="mb-3 flex justify-between text-xs font-bold"><span class="text-wiki">← More frequent in Wikipedia</span><span class="text-brit">More frequent in Britannica →</span></div>
      <div class="relative"><div class="absolute inset-y-0 left-1/2 w-px bg-line"></div>${bars}</div>`, 'lg:col-span-2')}
    ${card('Method', `
      <div class="grid grid-cols-2 gap-2">${stat('Matched pairs', d.pairs_used)}${stat('Terms kept', d.terms.length)}
        ${stat('Britannica tokens', d.brit_tokens.toLocaleString())}${stat('Wikipedia tokens', d.wiki_tokens.toLocaleString())}</div>
      <p class="mt-4 text-sm"><span class="font-bold">Method:</span> <code>${esc(d.method)}</code></p>
      <p class="mt-2 text-sm"><span class="font-bold">Exclusions:</span> ${d.exclusions.length ? d.exclusions.map(esc).join(', ') : 'none'}</p>`)}
    ${card('Dual-quote viewer · strongest shifts', `<div class="grid gap-6 xl:grid-cols-2">` + quotes.map(t => `
      <div><h3 class="mb-2 font-serif text-xl font-semibold italic">${esc(t.term)}</h3>
      <div class="grid gap-3 md:grid-cols-2">
        <blockquote class="rounded-lg border-l-4 border-brit bg-brit-soft/60 p-4 font-serif text-[17px] italic leading-snug">“${esc(t.brit_example.quote)}”
          <div class="mt-3 font-sans not-italic">${britChip(t.brit_example.entry_id)}</div></blockquote>
        <blockquote class="rounded-lg border-l-4 border-wiki bg-wiki-soft/60 p-4 text-[15px] leading-snug">“${esc(t.wiki_example.quote)}”
          <div class="mt-3">${wikiChip(t.wiki_example.page_id, t.wiki_example.revision_id)}</div></blockquote>
      </div></div>`).join('') + `</div>`, 'lg:col-span-3')}
  </div>`;
}

// ---------- 4. Agent Console ----------
// Replays saved Hermes runs. Live questions run in the Hermes CLI; the site never calls a model.
const prettyJson = s => { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } };
const citeInline = text => esc(text)
  .replace(/\[B:([\w-]+)\]/g, (_, id) => britChip(id, id))
  .replace(/\[W:(\d+)@(\d+)\]/g, (_, p, r) => wikiChip(p, r, `${p}@${r}`));
const citationChip = c => {
  if ((c.source || '').toLowerCase().startsWith('brit')) return britChip(c.id ?? c.entry_id, c.id ?? c.entry_id);
  const [p, r] = String(c.id ?? '').split('@');
  return wikiChip(c.page_id ?? p, c.revision_id ?? r);
};

let replayTimer;
function agent(q) {
  clearTimeout(replayTimer);
  if (!D.runs.length) return ($view.innerHTML = empty('No agent runs yet. Run <code>nemotron-challenge run agent</code> and <code>run site</code>.'));
  const r = D.runs.find(x => x.run_id === q.get('r')) || D.runs[0];
  const role = (who, cls) => `<p class="mb-1 text-[11px] font-bold uppercase tracking-wider ${cls}">${who}</p>`;
  const verdict = {
    success: `<p class="mb-3 inline-flex items-center gap-1.5 rounded-full bg-ok-soft px-3 py-1 text-xs font-bold text-ok">${icon('check', 'h-3.5 w-3.5')} Reviewed · success</p>`,
    failure: `<p class="mb-3 inline-flex items-center gap-1.5 rounded-full bg-bad px-3 py-1 text-xs font-bold text-white">${icon('ban', 'h-3.5 w-3.5')} Reviewed · failure</p>`,
    unreviewed: `<p class="mb-3 inline-flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs font-bold text-sub">${icon('dot', 'h-3.5 w-3.5')} Not reviewed</p>`,
  }[r.label];

  const steps = [
    `<div class="rise ml-auto max-w-2xl">${role('Researcher', 'text-right text-sub')}<div class="rounded-xl rounded-tr-sm bg-wiki p-4 text-white">${esc(r.question)}</div></div>`,
    ...r.image_inputs.map(path => {
      const e = entryByCrop(path);
      return `<div class="rise flex items-center gap-4 rounded-xl border border-line bg-card p-3 text-sm">
        <span class="relative flex h-16 w-16 shrink-0 items-center justify-center rounded bg-muted text-sub">${icon('image', 'h-8 w-8')}
          ${e ? `<img src="${esc(cropUrl(e))}" alt="" class="absolute inset-0 h-16 w-16 rounded bg-muted object-contain" onerror="this.remove()">` : ''}</span>
        <div>${role('Image input → Super VL', 'text-sub')}${e ? `<b>${esc(label(e))}</b> <span class="text-sub">· ${esc(e.entry_id)}</span>` : `<span class="font-mono text-xs">${esc(path)}</span>`}</div></div>`;
    }),
    ...r.tool_calls.map(t => `<div class="rise rounded-xl border ${t.error ? 'border-bad/40 bg-bad-soft' : 'border-tool/30 bg-tool-soft'} p-4 text-sm">
      <p class="flex items-center gap-2 font-bold ${t.error ? 'text-bad' : 'text-tool'}">${icon(t.error ? 'warn' : 'wrench')} Tool call${t.error ? ' · error' : ''}</p>
      <code class="mt-1 block font-mono text-[13px] text-tool">${esc(t.name)}(${esc(JSON.stringify(t.arguments))})</code>
      <pre class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-card p-3 font-mono text-xs text-fg">${esc(t.error ?? prettyJson(t.result))}</pre></div>`),
    `<div class="rise max-w-3xl">${role(`Hermes · ${esc(r.model)}`, 'text-sub')}
      <div class="rounded-xl rounded-tl-sm border-2 ${r.label === 'failure' ? 'border-bad' : r.label === 'success' ? 'border-ok' : 'border-line'} bg-card p-5">
      ${verdict}
      <p class="text-[15px] leading-relaxed">${citeInline(r.answer)}</p>
      ${r.citations.length ? `<div class="mt-4 flex flex-wrap gap-2 border-t border-line pt-3">${r.citations.map(citationChip).join('')}</div>` : ''}
      ${r.notes ? `<p class="mt-3 text-xs text-sub"><span class="font-bold">Review note:</span> ${esc(r.notes)}</p>` : ''}</div></div>`,
  ];

  const tab = x => `<a href="#agent?r=${encodeURIComponent(x.run_id)}" class="${btn(x === r, x.label === 'success' ? 'bg-ok text-white' : x.label === 'failure' ? 'bg-bad text-white' : 'bg-wiki text-white')} inline-flex items-center gap-1.5">
    ${icon(x.label === 'success' ? 'check' : x.label === 'failure' ? 'ban' : 'dot', 'h-3.5 w-3.5')}${esc(x.run_id)}</a>`;
  $view.innerHTML = `
    <div class="mb-5 flex flex-wrap items-center gap-1.5">
      ${D.runs.map(tab).join('')}
      <button id="replay" class="ml-auto inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-brit px-4 py-1.5 text-sm font-bold text-white transition-colors hover:bg-brit/90">${icon('play', 'h-3.5 w-3.5')} Replay</button>
    </div>
    <p class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-sub">
      <span class="font-bold uppercase tracking-[0.12em]">Recorded run</span>
      <span>${esc(new Date(r.started_at).toLocaleString())}</span><span>${esc(r.hermes_version)}</span>
      <span>tools ${r.tools_enabled ? 'on' : 'off'}</span><span>finish: ${esc(r.finish_reason)}</span>
      <span class="font-mono">rev ${esc(r.code_revision.slice(0, 7))}</span></p>
    <div id="stream" class="mx-auto flex max-w-4xl flex-col gap-4" aria-live="polite"></div>`;

  const stream = document.getElementById('stream');
  const show = (i = 0) => { stream.innerHTML = steps.slice(0, i).join(''); if (i < steps.length) replayTimer = setTimeout(() => show(i + 1), 800); };
  stream.innerHTML = steps.join('');
  document.getElementById('replay').onclick = () => { clearTimeout(replayTimer); show(1); };
}

// ---------- 5. Reading Check ----------
// Parse 3.5 reads the scan; Super VL re-reads each block against the image; Embed VL checks the modern spelling keeps
// the meaning. Every number comes from the artifacts (coverage.json, ablation.json, matches.jsonl) via `run site`.
const pct1 = n => (n == null ? '–' : `${(n * 100).toFixed(1)}%`);
function reading() {
  const Q = D.quality;
  if (!Q?.correction) return ($view.innerHTML = empty('No correction results yet. Run <code>EXTRACT_CORRECT=1 nemotron-challenge run extract</code> and <code>run site</code>.'));
  const g = (Q.correction.gold || [])[0];
  const c = Q.correction;
  const accepted = c.blocks_sent - c.blocks_with_fallback;
  const big = (title, before, after, note) => `<section class="rise rounded-xl border border-line bg-card p-5 shadow-sm">
      <h2 class="text-xs font-bold uppercase tracking-[0.12em] text-sub">${title}</h2>
      <p class="mt-3 flex items-baseline gap-3"><span class="text-2xl text-sub line-through decoration-brit/70">${before}</span>
        <span class="text-sub">→</span><span class="text-4xl font-bold text-ok">${after}</span></p>
      <p class="mt-3 text-sm text-sub">${note}</p></section>`;
  const m = Q.matching;
  const ab = Q.ablation?.methods;
  const abRows = ab ? [['BM25 only', ab.bm25_only], ['+ Embed VL', ab.bm25_embed], ['+ Rerank VL', ab.bm25_embed_rerank]] : [];
  const fixes = Q.verified_fixes.slice(0, 16).map(f => `
      <tr class="border-t border-line">
        <td class="py-2 pr-4 font-serif text-[17px] text-bad line-through decoration-2">${esc(f.parse)}</td>
        <td class="py-2 pr-4 font-serif text-[17px] font-bold text-ok">${esc(f.super_vl)}</td>
        <td class="py-2 text-right text-xs"><a class="text-wiki underline-offset-2 hover:underline" href="#viewer?p=${f.row_index}&e=${f.entry_id}">row ${f.row_index} →</a></td></tr>`).join('');

  $view.innerHTML = `
    <p class="mb-5 max-w-3xl text-sub">The OCR model sometimes swaps old words for plausible modern ones. A second Nemotron model re-reads every
      block against the scan image. Parse's text is never overwritten: the PDFs show both readings, struck through and bold.</p>
    <div class="grid gap-5 lg:grid-cols-3">
      ${g ? big('OCR errors · hand-checked page', pct1(g.cer_parse), pct1(g.cer_faithful),
        `${g.errors_parse} → ${g.errors_faithful} character errors in ${g.gold_chars} characters (row ${g.row_index}).
         Super VL also changed ${g.overcorrected_words} words that Parse had right.`) : ''}
      ${m?.modern_text ? big('Entries matched to Wikipedia', m.parse_text.matched ?? 0, m.modern_text.matched ?? 0,
        `Same match stage and thresholds, run on the corrected modern text. A first review finds most new matches right and some wrong:
         see <code>artifacts/match/modern/COMPARISON.md</code>.`) : ''}
      ${abRows.length ? card(`Top-1 accuracy · ${Q.ablation.labeled} labeled entries`, abRows.map(([name, r]) => `
        <div class="mb-3"><div class="flex justify-between text-sm"><span>${name}</span><span class="font-bold tabular-nums">${pct1(r.top1_accuracy)}</span></div>
          <div class="mt-1.5 h-2.5 rounded-full bg-muted"><div class="h-2.5 rounded-full bg-wiki" style="width:${pct(r.top1_accuracy)}"></div></div></div>`).join('') +
        `<p class="mt-2 text-xs text-sub">Same BM25 candidate pool in every row. Labels are on P2's development entries.</p>`) : ''}
    </div>
    <div class="mt-5 grid gap-5 lg:grid-cols-3">
      ${card('Fixes confirmed by the hand-typed page', fixes
        ? `<table class="w-full text-left"><thead><tr class="text-[11px] uppercase tracking-wider text-sub"><th class="pb-2">Parse 3.5 read</th><th class="pb-2">Super VL corrected</th><th></th></tr></thead><tbody>${fixes}</tbody></table>
           <p class="mt-3 text-xs text-sub">Listed only when the corrected words line up with the same words in the hand transcription.</p>`
        : '<p class="text-sm text-sub">No gold transcription yet.</p>', 'lg:col-span-2')}
      ${card('How the check works', `
        <ol class="space-y-3 text-sm">
          <li><b>1. Parse 3.5</b> reads the scan into blocks with boxes.</li>
          <li><b>2. Super VL</b> (${esc(c.model ?? '')}) gets each block's scan region and Parse's text, and returns a
            <i>faithful</i> version (old spelling kept) and a <i>modern</i> one.</li>
          <li><b>3. Embed VL</b> checks the modern version keeps the meaning (cosine ≥ ${c.meaning_check?.threshold}); if not, the faithful text is kept.</li>
          <li><b>4. Guardrails</b> keep Parse's text when a reply adds or drops words.</li></ol>
        <div class="mt-4 grid grid-cols-2 gap-2">${stat('Blocks checked', c.blocks_sent)}${stat('Accepted', accepted, 'text-ok')}
          ${stat('Meaning check median', fmt(c.meaning_check?.median))}${stat('Fallbacks', c.blocks_with_fallback, 'text-brit')}</div>
        ${g ? `<a href="#viewer?p=${g.row_index}" class="mt-4 inline-block text-sm font-bold text-brit underline-offset-2 hover:underline">See the corrections in the compiled PDF →</a>` : ''}`)}
    </div>`;
}

// ---------- Pipeline ----------
const pipeline = () => { $view.innerHTML = `<iframe src="architecture.html" title="Pipeline architecture" class="h-[84vh] w-full rounded-xl border border-line bg-card"></iframe>`; };

// ---------- Router ----------
const routes = { viewer, reading, match, analytics, agent, pipeline };
function route() {
  const [name, qs] = location.hash.slice(1).split('?');
  const r = routes[name] ? name : 'viewer';
  document.querySelectorAll('#nav a').forEach(a => {
    const on = a.hash === '#' + r;
    a.className = `rounded-md px-3 py-2 transition-colors ${on ? 'bg-wiki font-bold text-white' : 'text-sub hover:bg-muted hover:text-fg'}`;
    on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current');
  });
  routes[r](new URLSearchParams(qs));
}

const quality = fetch('data/quality.json').then(r => (r.ok ? r.json() : null)).catch(() => null);  // optional
Promise.all([...['pages', 'drift', 'cases'].map(f => fetch(`data/${f}.json`).then(r => { if (!r.ok) throw new Error(`${f}.json: HTTP ${r.status}`); return r.json(); })), quality])
  .then(([pages, drift, runs, q]) => { D = { pages, drift, runs, quality: q }; addEventListener('hashchange', route); route(); })
  .catch(err => { $view.innerHTML = `<p class="text-bad">Failed to load data (${esc(err.message)}). Serve the folder over HTTP: <code>python3 -m http.server -d web</code></p>`; });
