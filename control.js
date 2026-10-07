// Finestra di controllo: legge lo stato da Python ogni secondo e lo mostra.

const $ = id => document.getElementById(id);
const api = () => window.pywebview.api;
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const clock = sec => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;

let editing = false;   // non sovrascrivere il campo mentre l'utente scrive

// stati di una parola: chiave, nome, spiegazione, classe colore
const GROUPS = [
  ['learned', 'Imparate', '4 risposte giuste di fila', 'g-learned'],
  ['almost', 'Quasi imparate', '2 o 3 risposte giuste di fila', 'g-almost'],
  ['weak', 'Da ripassare', 'già chieste, ma con meno di 2 risposte giuste di fila', 'g-weak'],
  ['new', 'Mai viste', 'non ti sono ancora state chieste', 'g-new'],
];
const GROUP_NAME = Object.fromEntries(GROUPS.map(g => [g[0], g[1]]));
const GROUP_CLASS = Object.fromEntries(GROUPS.map(g => [g[0], g[3]]));

/* ---------- schede ---------- */

function selectTab(name) {
  document.querySelectorAll('[role=tab]').forEach(t => {
    const on = t.id === 't-' + name;
    t.setAttribute('aria-selected', on);
    t.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll('.panel').forEach(p => { p.hidden = p.id !== 'p-' + name; });
  $('count').textContent = '';
  hideNotice();
  if (name === 'words') loadWords();
}

function initTabs() {
  const tabs = [...document.querySelectorAll('[role=tab]')];
  tabs.forEach((t, i) => {
    t.addEventListener('click', () => selectTab(t.id.slice(2)));
    t.addEventListener('keydown', e => {
      const d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!d) return;
      const next = tabs[(i + d + tabs.length) % tabs.length];
      next.focus();
      selectTab(next.id.slice(2));
    });
  });
}

/* ---------- studio e progressi ---------- */

function renderProgress(sum) {
  const g = sum.groups;
  $('learned').textContent = g.learned;
  $('ofTotal').textContent = `parole su ${sum.total} imparate`;
  $('stack').innerHTML = GROUPS.map(([k, , , cls]) =>
    `<i class="${cls}" style="flex-grow:${g[k]}" title="${GROUP_NAME[k]}: ${g[k]}"></i>`).join('');
  $('legend').innerHTML = GROUPS.map(([k, name, why, cls]) =>
    `<li><span class="dot ${cls}"></span><span class="name">${name}</span><span class="n num">${g[k]}</span>`
    + `<span class="why">${why}</span></li>`).join('');

  $('hardestBox').hidden = !sum.hardest.length;
  $('hardest').innerHTML = sum.hardest.map(h =>
    `<li><strong>${esc(h.label)}</strong><span class="it">${esc(h.it)}</span>`
    + `<span class="miss">${plural(h.wrong, 'errore', 'errori')}</span></li>`).join('');
  $('streak').textContent = sum.streak
    ? `Serie attiva: ${plural(sum.streak, 'giorno', 'giorni')} di fila con almeno una risposta.` : '';
}

/* ---------- sezioni da cui escono le domande ---------- */

let scopeState = { categories: [], selected: [], words: 0, fallback: false };

function renderScope(sc) {
  scopeState = sc;
  const all = !sc.selected.length;
  const chip = (key, label, n, on) =>
    `<button class="chip" type="button" data-cat="${esc(key)}" aria-pressed="${on}">${esc(label)}<span class="c">${n}</span></button>`;
  const total = sc.categories.reduce((a, c) => a + c.count, 0);
  $('scope').innerHTML = chip('', 'Tutte', total, all)
    + sc.categories.map(c => chip(c.name, c.name, c.count, sc.selected.includes(c.name))).join('');
  const note = $('scopeNote');
  note.classList.toggle('warn', sc.fallback || sc.words < 4);
  note.textContent = sc.fallback
    ? 'Le sezioni scelte non hanno più parole: per ora escono domande da tutte.'
    : all ? `Le domande escono da tutte le sezioni (${plural(sc.words, 'parola', 'parole')}).`
    : sc.words < 4 ? `Solo ${plural(sc.words, 'parola', 'parole')} in queste sezioni: le domande si ripeteranno spesso.`
    : `Le domande escono solo da ${sc.selected.length === 1 ? 'questa sezione' : 'queste sezioni'} (${plural(sc.words, 'parola', 'parole')}).`;
}

async function toggleScope(cat) {
  let sel = [...scopeState.selected];
  if (!cat) sel = [];                                   // «Tutte»
  else if (sel.includes(cat)) sel = sel.filter(c => c !== cat);  // l'ultima tolta = di nuovo «Tutte»
  else sel.push(cat);
  renderScope(await api().set_scope(sel));  // lo stato nuovo arriva subito: un secondo clic parte da quello
  refresh();
}

function render(s) {
  const box = $('next');
  box.classList.toggle('paused', s.state === 'paused');
  box.classList.toggle('asking', s.state === 'asking');
  $('stateLabel').textContent = s.state === 'paused' ? 'In pausa'
    : s.state === 'asking' ? 'Domanda in corso' : 'Prossima domanda tra';
  $('countdown').textContent = s.state === 'waiting' ? clock(s.seconds_left) : '–:––';
  $('pause').textContent = s.state === 'paused' ? 'Riprendi' : 'Pausa';
  $('askNow').disabled = s.state === 'asking';

  if (!editing) $('interval').value = s.interval;
  document.querySelectorAll('input[name=level]').forEach(r => { r.checked = r.value === s.level_mode; });

  renderScope(s.scope);
  renderProgress(s.summary);
  const t = s.today;
  $('today').textContent = t.seen ? `Oggi: ${t.right} giuste su ${t.seen}` : 'Oggi: ancora nessuna risposta.';
}

async function refresh() {
  try { render(await api().status()); } catch (e) { /* finestra in chiusura */ }
}

/* ---------- elenco parole ---------- */

let words = [];
let filter = 'all';
let query = '';
// «huegel» e «hugel» trovano entrambe «Hügel»; lo stesso per ä/ö/ß e per gli accenti italiani
const strip = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '');
const expand = s => s.replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss');
const variants = s => { const l = s.toLowerCase(); return [strip(expand(l)), strip(l).replace(/ß/g, 'ss')]; };
const matches = (hay, q) => variants(hay).some(h => variants(q).some(v => h.includes(v)));

async function loadWords() {
  words = await api().words();
  renderChips();
  renderList();
}

function renderChips() {
  const active = words.filter(w => !w.removed);
  const count = k => k === 'all' ? active.length : k === 'removed' ? words.length - active.length
    : active.filter(w => w.status === k).length;
  const chips = [['all', 'Tutte'], ...GROUPS.map(g => [g[0], g[1]])];
  if (count('removed')) chips.push(['removed', 'Rimosse']);
  else if (filter === 'removed') filter = 'all';
  $('chips').innerHTML = chips.map(([k, name]) =>
    `<button class="chip" data-k="${k}" aria-pressed="${filter === k}">${name}<span class="c">${count(k)}</span></button>`).join('');
}

function wordHtml(w) {
  const art = w.article ? `<span class="art ${w.article}">${w.article}</span>` : '';
  const stats = (w.right || w.wrong) ? `${w.right} giuste · ${w.wrong} sbagliate` : 'mai chiesta';
  const action = w.removed
    ? `<button class="link" type="button" data-restore="${w.id}">Rimetti nelle domande</button>`
    : `<button class="link danger" type="button" data-remove="${w.id}">Togli dalle domande</button>`;
  return `<details class="word${w.removed ? ' is-removed' : ''}" data-id="${w.id}">
    <summary><span class="dot ${GROUP_CLASS[w.status]}" title="${GROUP_NAME[w.status]}"></span>
      <span class="de">${art}${esc(w.de)}${w.custom ? '<span class="tag">tua</span>' : ''}</span><span class="it">${esc(w.it.join(', '))}</span></summary>
    <div class="more">
      ${w.extra ? `<p class="muted">${esc(w.extra)}</p>` : ''}
      ${w.tip ? `<p class="tip">${esc(w.tip)}</p>` : ''}
      <p class="meta"><span>${GROUP_NAME[w.status]} · ${stats}</span>
        <button class="link" type="button" data-say="${esc((w.article ? w.article + ' ' : '') + w.de)}">Ascolta</button>${action}</p>
    </div></details>`;
}

function renderList() {
  const q = query.trim();
  const shown = words.filter(w =>
    (filter === 'removed' ? w.removed : !w.removed && (filter === 'all' || w.status === filter))
    && (!q || matches(w.de, q) || w.it.some(t => matches(t, q))));
  const total = words.filter(w => filter === 'removed' ? w.removed : !w.removed).length;
  $('count').textContent = `${shown.length} di ${total} parole`;
  if (!shown.length) {
    $('list').innerHTML = `<p class="empty">${q ? 'Nessuna parola trovata.' : 'Nessuna parola qui.'}</p>`;
    return;
  }

  const open = new Set([...document.querySelectorAll('.word[open]')].map(d => d.dataset.id));
  let html = '', cat = null;
  for (const w of shown) {
    if (w.category !== cat) { cat = w.category; html += `<div class="group-title">${esc(cat)}</div>`; }
    html += wordHtml(w);
  }
  $('list').innerHTML = html;
  open.forEach(id => { const d = $('list').querySelector(`.word[data-id="${id}"]`); if (d) d.open = true; });
}

/* ---------- aggiungere e togliere parole ---------- */

function showNotice(text, undoId) {
  const n = $('notice');
  n.innerHTML = `<span>${esc(text)}</span>` + (undoId ? `<button class="link" type="button" data-undo="${undoId}">Annulla</button>` : '');
  n.hidden = false;
}
const hideNotice = () => { $('notice').hidden = true; };

const NEW_CATEGORY = '__new__';
let lastCategory = '';   // l'ultima categoria usata: comoda quando inserisci più parole della stessa lezione

async function fillCategories(selected) {
  const { list, default: def } = await api().categories();
  const pick = selected || lastCategory || def;
  $('fCategory').innerHTML = list.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('')
    + `<option value="${NEW_CATEGORY}">+ Nuova categoria…</option>`;
  $('fCategory').value = list.includes(pick) ? pick : def;
  toggleNewCategory();
}

function toggleNewCategory() {
  const isNew = $('fCategory').value === NEW_CATEGORY;
  $('fNewCategory').hidden = !isNew;
  if (isNew) $('fNewCategory').focus();
}

async function setAddOpen(open) {
  $('addForm').hidden = !open;
  $('addToggle').setAttribute('aria-expanded', open);
  if (open) { await fillCategories(); $('fDe').focus(); return; }
  $('addForm').reset();
  $('fNewCategory').hidden = true;
  $('addError').textContent = '';
  document.querySelectorAll('.add .invalid').forEach(i => i.classList.remove('invalid'));
}

async function submitAdd(e) {
  e.preventDefault();
  if ($('fCategory').value === NEW_CATEGORY && !$('fNewCategory').value.trim()) {
    $('addError').textContent = 'Scrivi il nome della nuova categoria, oppure scegline una dall’elenco.';
    $('fNewCategory').classList.add('invalid');
    $('fNewCategory').focus();
    return;
  }
  const res = await api().add_word({
    article: $('fArticle').value, de: $('fDe').value, plural: $('fPlural').value,
    it: $('fIt').value, tip: $('fTip').value,
    category: $('fCategory').value === NEW_CATEGORY ? $('fNewCategory').value : $('fCategory').value,
  });
  document.querySelectorAll('.add .invalid').forEach(i => i.classList.remove('invalid'));
  if (!res.ok) {
    $('addError').textContent = res.error;
    const bad = $(res.field === 'it' ? 'fIt' : 'fDe');
    bad.classList.add('invalid');
    bad.focus();
    return;
  }
  lastCategory = res.category;
  setAddOpen(false);
  filter = 'all';
  query = '';
  $('search').value = '';
  await loadWords();
  refresh();
  showNotice(`«${res.label}» aggiunta in «${res.category}»: la riceverai nelle domande.`);
  const row = $('list').querySelector(`.word[data-id="${res.id}"]`);
  if (row) row.scrollIntoView({ block: 'nearest' });
}

async function removeWord(id) {
  const res = await api().remove_word(id);
  if (!res.ok) return showNotice(res.error);
  await loadWords();
  refresh();
  showNotice(`«${res.label}» non uscirà più nelle domande.`, id);
}

async function restoreWord(id) {
  const res = await api().restore_word(id);
  await loadWords();
  refresh();
  showNotice(res.ok ? `«${res.label}» è tornata nelle domande.` : res.error);
}

function initWords() {
  $('search').addEventListener('input', e => { query = e.target.value; renderList(); });
  $('chips').addEventListener('click', e => {
    const b = e.target.closest('.chip');
    if (!b) return;
    filter = b.dataset.k;
    renderChips();
    renderList();
  });

  $('addToggle').addEventListener('click', () => setAddOpen($('addForm').hidden));
  $('addCancel').addEventListener('click', () => { setAddOpen(false); $('addToggle').focus(); });
  $('addForm').addEventListener('submit', submitAdd);
  $('fCategory').addEventListener('change', toggleNewCategory);
  $('addForm').addEventListener('keydown', e => {
    if (e.key === 'Escape') { setAddOpen(false); $('addToggle').focus(); }
  });

  $('notice').addEventListener('click', e => {
    const b = e.target.closest('[data-undo]');
    if (b) restoreWord(b.dataset.undo);
  });
  $('list').addEventListener('click', e => {
    const say = e.target.closest('[data-say]');
    if (say) return speakDe(say.dataset.say);
    const rm = e.target.closest('[data-remove]');
    if (rm) return removeWord(rm.dataset.remove);
    const back = e.target.closest('[data-restore]');
    if (back) restoreWord(back.dataset.restore);
  });
}

/* ---------- avvio ---------- */

window.addEventListener('pywebviewready', () => {
  initTabs();
  initWords();
  refresh();
  setInterval(refresh, 1000);

  $('scope').addEventListener('click', e => {
    const b = e.target.closest('[data-cat]');
    if (b) toggleScope(b.dataset.cat);
  });
  $('askNow').onclick = async () => { await api().ask_now(); refresh(); };
  $('pause').onclick = async () => { await api().toggle_pause(); refresh(); };
  $('quit').onclick = () => api().quit();
  $('reset').onclick = async () => {
    if (confirm('Vuoi azzerare tutti i progressi? Le parole che hai aggiunto o tolto restano come sono.')) {
      await api().reset();
      refresh();
    }
  };

  const interval = $('interval');
  interval.addEventListener('focus', () => { editing = true; });
  interval.addEventListener('blur', () => { editing = false; });
  interval.addEventListener('change', async () => {
    const v = parseInt(interval.value, 10);
    if (v >= 1 && v <= 240) await api().set_interval(v);
    refresh();
  });
  document.querySelectorAll('input[name=level]').forEach(r =>
    r.addEventListener('change', () => api().set_level(r.value)));
});
