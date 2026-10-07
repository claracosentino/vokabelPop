// Banner: mostra la domanda e la risposta. Tutta la logica sta in Python (bridge.py).

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const stars = (n, max) => '★'.repeat(n) + '☆'.repeat(max - n);

let q = null;        // domanda corrente
let answered = false;
let leaving = false;

const api = () => window.pywebview.api;

function germanHtml(article, de) {
  return (article ? `<span class="art ${article}">${esc(article)}</span>` : '') + `<span class="${article || ''}">${esc(de)}</span>`;
}

function showQuestion() {
  const it2de = q.direction === 'it2de';
  const hard = q.level === 'hard';

  $('meta').innerHTML = `${it2de ? 'IT → DE' : 'DE → IT'} · ${hard ? 'difficile' : 'facile'}`
    + `<span class="stars">${stars(q.box, q.max_box)}</span>`;
  $('eyebrow').textContent = it2de ? 'Come si dice in tedesco?' : 'Cosa vuol dire?';
  $('prompt').innerHTML = it2de ? esc(q.prompt) : germanHtml(q.article, q.de);
  $('note').textContent = hard && q.ask_article ? 'Scrivi anche l’articolo: der, die o das.' : '';

  $('choices').hidden = hard;
  $('typed').hidden = !hard;
  $('tools').hidden = !hard;

  if (hard) {
    $('answer').focus();
  } else {
    $('choices').innerHTML = q.options.map((o, i) => {
      const art = it2de ? o.split(' ')[0] : '';
      const cls = ['der', 'die', 'das'].includes(art) ? art : '';
      return `<button class="choice" data-i="${i}"><kbd>${i + 1}</kbd><span class="${cls}">${esc(o)}</span></button>`;
    }).join('');
  }
}

async function choose(i) {
  if (answered) return;
  showResult(await api().choose(i));
}

async function submit() {
  if (answered) return;
  const r = await api().submit($('answer').value);
  if (r) showResult(r);
}

async function showHint() {
  $('hinttext').textContent = await api().hint();
  $('hint').disabled = true;
}

async function giveUp() {
  if (answered) return;
  showResult(await api().give_up());
}

function showResult(r) {
  if (!r) return;
  answered = true;
  $('question').hidden = true;
  $('result').hidden = false;
  document.title = 'Vokabel-Pop';

  const v = $('verdict');
  v.className = 'verdict ' + (r.good ? 'ok' : 'bad');
  v.textContent = r.result === 'typo' ? 'Quasi giusto: attento all’ortografia'
    : r.good ? (r.hint_used ? 'Giusto, con aiutino' : 'Giusto') : 'Non proprio';
  $('given').textContent = !r.good && r.given ? `Hai risposto: ${r.given}` : '';
  $('problem').textContent = r.message || '';

  $('de').innerHTML = germanHtml(r.article, r.de);
  $('extra').textContent = r.extra || '';
  $('it').textContent = '= ' + r.it.join(', ');
  $('tip').hidden = !r.tip;
  $('tiptext').textContent = r.tip || '';

  say = r.say;
  $('ok').focus();
}

let say = '';

async function leave(reason) {
  if (leaving) return;
  leaving = true;
  document.querySelector('.card').classList.add('leaving');
  await new Promise(r => setTimeout(r, 220));
  api().dismiss(reason);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') return leave(answered ? 'answered' : 'skip');
  if (answered) { if (e.key === 'Enter') leave('answered'); return; }
  if (q && q.level === 'easy' && /^[1-4]$/.test(e.key)) choose(+e.key - 1);
});

// Il banner non ruba la tastiera quando compare. Al primo clic però deve prenderla, altrimenti
// i tasti continuano ad andare al programma che stavi usando e il campo di testo resta muto.
let activating = false;
document.addEventListener('mousedown', async () => {
  if (activating || leaving || !window.pywebview) return;
  activating = true;
  try {
    await api().activate();
    if (q && q.level === 'hard' && !answered) $('answer').focus();
  } finally {
    setTimeout(() => { activating = false; }, 300);
  }
}, true);

window.addEventListener('pywebviewready', async () => {
  q = await api().question();
  showQuestion();
});

$('choices').addEventListener('click', e => {
  const b = e.target.closest('.choice');
  if (b) choose(+b.dataset.i);
});
$('typed').addEventListener('submit', e => { e.preventDefault(); submit(); });
$('hint').addEventListener('click', showHint);
$('dunno').addEventListener('click', giveUp);
$('close').addEventListener('click', () => leave('skip'));
$('skip').addEventListener('click', () => leave('skip'));
$('later').addEventListener('click', () => leave('snooze'));
$('ok').addEventListener('click', () => leave('answered'));
$('listen').addEventListener('click', () => speakDe(say));

// la finestra segue l'altezza del contenuto (domanda e risposta hanno altezze diverse)
let lastHeight = 0;
async function reportSize() {
  const h = Math.ceil(document.querySelector('.card').getBoundingClientRect().height);
  if (!h || h === lastHeight || !window.pywebview) return;
  if (await api().fit(400, h)) lastHeight = h;
  else setTimeout(reportSize, 100);  // Python non era pronto: riprova
}
new ResizeObserver(reportSize).observe(document.querySelector('.card'));
window.addEventListener('pywebviewready', reportSize);
