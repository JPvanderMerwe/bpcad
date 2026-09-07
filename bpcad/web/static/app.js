/*
 * bpcad client. Brief 9.7: one frontend, three deliveries.
 *
 * No framework and no build step. The surface is one prompt, one viewport, a
 * strip and a sheet, and a framework to hold that would be more code than the
 * thing it holds — plus a build step, which is one more way for the app to be
 * broken on a machine with no internet.
 *
 * TWO RULES FROM SECTION 11 LIVE IN HERE RATHER THAN IN THE CSS
 * --------------------------------------------------------------
 * 11.5.4 — the glass blur must DROP to a flat tint while the model is being
 * rotated or a slider dragged, and come back on settle. That is a class on
 * <body> toggled by the interaction handlers, because CSS cannot know when a
 * drag starts.
 *
 * 11.4 — a numeric value is an INPUT, not a readout. Every slider has a
 * tappable field beside it. A maker knows the exact number and hunting for it
 * with a thumb is an insult.
 */

'use strict';

const $ = (id) => document.getElementById(id);

/* Brief 6: speed is a feature and honesty about it is a bigger one. These are
 * the real stages the engine reports; the bar steps when one completes and
 * then waits, rather than creeping to 99% and lying. */
const STAGES = [
  { key: 'Thinking',  match: /using|attempt|started/i,            at: 12 },
  { key: 'Composing', match: /primitives|template|no templ/i,     at: 34 },
  { key: 'Building',  match: /building geometry/i,                at: 58 },
  { key: 'Checking',  match: /verify|checking|export/i,           at: 74 },
  { key: 'Options',   match: /building options/i,                 at: 86 },
];

const state = {
  part: null, frames: [], frameCount: 24, step: 0,
  job: null, started: 0, timer: null, stage: -1,
  options: [], capability: {}, library: [], renderVersion: 1,
};

const frameUrl = (name, step, width) =>
  '/api/part/' + encodeURIComponent(name) + '/frame/' + step +
  '?w=' + width + '&v=' + state.renderVersion;

/* ── plumbing ────────────────────────────────────────────────────────── */

async function api(path, options) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch { throw new Error('the server sent something that is not JSON'); }
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}
const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/* 11.5.4. Held for a moment after the last event so a stuttering drag does not
   flick the blur on and off, which is worse than either state. */
let settleTimer = null;
function interacting(on) {
  clearTimeout(settleTimer);
  if (on) { document.body.classList.add('interacting'); return; }
  settleTimer = setTimeout(() => document.body.classList.remove('interacting'), 180);
}

function log(text) {
  for (let i = STAGES.length - 1; i >= 0; i--) {
    if (STAGES[i].match.test(text) && i > state.stage) {
      state.stage = i;
      $('stageName').textContent = STAGES[i].key;
      $('track').style.width = STAGES[i].at + '%';
      break;
    }
  }
  const el = $('log');
  el.textContent += new Date().toTimeString().slice(0, 8) + '  ' + text + '\n';
  el.scrollTop = el.scrollHeight;
}

/* ── startup ─────────────────────────────────────────────────────────── */

async function boot() {
  try {
    const health = await api('/api/health');
    const cap = health.capability || {};
  state.capability = cap;
    // Appended to every frame URL. See RENDER_VERSION in web/server.py: an
    // immutable cache plus a content-addressed URL means a renderer change
    // never reaches anybody without it.
    state.renderVersion = health.render_version || 1;

    const tier = cap.tier || 'cpu';
    $('lamp').className = 'lamp ' + (
      tier === 'gpu' ? 'ready' : tier === 'cpu' ? 'slow' : 'none');
    $('machineText').textContent =
      tier === 'gpu' ? (cap.gpu_name || 'GPU') + ' · fast'
      : tier === 'cpu' ? '~' + Math.round((cap.prompt_seconds || 155) / 60) + ' min a part'
      : 'No model';
    $('machine').title = cap.headline || '';

    // 11.7: state the wait plainly. Someone who is not told concludes it hung.
    if (cap.headline && tier !== 'gpu') {
      $('machineNote').textContent = cap.headline;
      $('machineNote').hidden = false;
      $('machineNote').className = 'note warn';
    }

    const printer = health.printer || {}, bed = health.bed || {};
    if (printer.name && bed.width_mm) {
      $('prompt').placeholder = 'Bracket to hold an 8 mm rod to a wall';
      $('machine').title += '  ·  ' + printer.name + ' ' +
        bed.width_mm + '×' + bed.depth_mm + '×' + bed.height_mm + ' mm';
    }
  } catch {
    $('lamp').className = 'lamp none';
    $('machineText').textContent = 'Not answering';
  }
  loadLibrary();
}

/* ── generating ──────────────────────────────────────────────────────── */

async function generate() {
  const request = $('prompt').value.trim();
  if (!request) { $('prompt').focus(); return; }

  $('generate').disabled = true;
  $('generate').textContent = 'Working';
  $('askBlock').hidden = true;
  $('workBlock').hidden = false;
  $('partBlock').hidden = true;
  $('optsBlock').hidden = true;
  $('opts').innerHTML = '';
  $('log').textContent = '';
  staging(null);          // a stale "could not render" must not outlive the part
  state.options = []; state.stage = -1;
  $('stageName').textContent = 'Thinking';
  $('track').style.width = '6%';

  const seconds = state.capability.prompt_seconds;
  $('stageEta').textContent = seconds
    ? (seconds > 90 ? 'about ' + Math.round(seconds / 60) + ' minutes on this machine'
                    : 'about ' + seconds + ' seconds')
    : '';
  $('lamp').className = 'lamp busy';
  startClock();
  log('> ' + request);

  try {
    const { job } = await post('/api/generate', { request, material: 'petg' });
    follow(job, (result) => finish(result));
  } catch (err) {
    log(err.message);
    finish(null);
  }
}

function finish(result) {
  stopClock();
  $('generate').disabled = false;
  $('generate').textContent = 'Generate';
  $('askBlock').hidden = false;
  $('track').style.width = '100%';
  $('lamp').className = 'lamp ' +
    (state.capability.tier === 'gpu' ? 'ready' : 'slow');

  if (result && result.ok) {
    $('stageName').textContent = 'Done';
    showPart(result);
    loadLibrary();
  } else {
    $('stageName').textContent = 'Nothing came out';
    log((result && result.message) || 'no part produced');
  }
}

async function refine() {
  const instruction = $('refine').value.trim();
  if (!instruction || !state.part) return;
  $('refineBtn').disabled = true;
  $('workBlock').hidden = false;
  startClock();
  log('> ' + instruction);
  try {
    const { job } = await post('/api/refine',
      { name: state.part.name, instruction });
    follow(job, (result) => {
      $('refineBtn').disabled = false;
      stopClock();
      if (result && result.ok) {
        (result.changes || []).forEach(log);
        $('refine').value = '';
        showPart(result);
        loadLibrary();
      } else {
        log((result && result.message) || 'could not apply that');
      }
    });
  } catch (err) {
    $('refineBtn').disabled = false;
    stopClock();
    log(err.message);
  }
}

/* The stream replays everything that already happened when it opens, so a
   phone that locked its screen comes back to the whole story. */
function follow(jobId, onDone) {
  const source = new EventSource('/api/job/' + jobId + '/events');
  state.job = source;
  let finished = false;

  source.onmessage = (message) => {
    let event;
    try { event = JSON.parse(message.data); } catch { return; }
    if (event.kind === 'option') addOption(event);
    else if (event.kind === 'note') log(event.text);
    else if (event.kind === 'started') log('started');
    else if (event.kind === 'failed' || event.kind === 'done') {
      finished = true; onDone(event);
    } else if (event.kind === 'closed') {
      source.close(); state.job = null;
      if (!finished) onDone(null);
    }
  };
  // A dropped connection is not a failed job — the work carries on server side.
  source.onerror = () => {
    source.close(); state.job = null;
    if (finished) return;
    api('/api/job/' + jobId)
      .then((j) => { if (j.done) onDone(j.result); else log('connection dropped, work continues'); })
      .catch(() => log('lost the connection'));
  };
}

function startClock() {
  state.started = Date.now();
  stopClock();
  state.timer = setInterval(() => {
    $('clock').textContent = Math.round((Date.now() - state.started) / 1000) + 's';
  }, 1000);
}
function stopClock() { if (state.timer) { clearInterval(state.timer); state.timer = null; } }

/* ── options ─────────────────────────────────────────────────────────── */

function addOption(option) {
  state.options.push(option);
  $('optsBlock').hidden = false;
  $('optsTitle').textContent = state.options.length === 1
    ? 'Options' : state.options.length + ' options';

  const card = document.createElement('button');
  card.className = 'opt waiting';
  card.type = 'button';

  const img = document.createElement('img');
  // EAGER. A lazy image appended to a panel revealed in the same tick may
  // never begin loading at all, and the card then shimmers for ever.
  img.loading = 'eager';
  img.decoding = 'async';
  img.alt = option.label || option.name;
  const settle = () => card.classList.remove('waiting');
  img.onload = settle; img.onerror = settle;
  img.src = frameUrl(option.name, 3, 320);
  if (img.complete) settle();

  const nm = document.createElement('div');
  nm.className = 'nm'; nm.textContent = option.label || option.name;
  const mm = document.createElement('div');
  mm.className = 'mm';
  if (option.envelope_mm) {
    mm.textContent = option.envelope_mm.map((v) => Math.round(v)).join(' × ') + ' mm';
  }

  card.append(img, nm, mm);
  card.addEventListener('click', () => {
    document.querySelectorAll('.opt').forEach((c) => c.removeAttribute('aria-current'));
    card.setAttribute('aria-current', 'true');
    openPart(option.name);
  });
  $('opts').appendChild(card);
}

/* ── the part ────────────────────────────────────────────────────────── */

function fact(key, value, tone) {
  const cell = document.createElement('div');
  cell.className = 'fact';
  const k = document.createElement('div'); k.className = 'k'; k.textContent = key;
  const v = document.createElement('div');
  v.className = 'v' + (tone ? ' ' + tone : ''); v.textContent = value;
  cell.append(k, v);
  return cell;
}

function showPart(part) {
  state.part = part;
  state.frames = [];
  $('partBlock').hidden = false;
  $('blank').hidden = true;
  $('partName').textContent = part.name;

  // 11.1: dimensions are the best-treated element on screen.
  const facts = $('facts');
  facts.innerHTML = '';
  if (part.size_mm) {
    const [x, y, z] = part.size_mm.map((v) => v.toFixed(1));
    facts.append(fact('Width', x + ' mm'), fact('Depth', y + ' mm'),
                 fact('Height', z + ' mm'));
  }
  if (part.volume_cm3 != null) facts.append(fact('Volume', part.volume_cm3 + ' cm³'));
  if (part.bodies != null) {
    facts.append(fact('Pieces', String(part.bodies), part.bodies === 1 ? '' : 'warn'));
  }
  if (part.material) facts.append(fact('Material', part.material));

  // 11.4: one-line printability strip.
  const verdict = (part.verdict || '').toUpperCase();
  if (verdict) {
    const bad = verdict.startsWith('FAIL');
    const warn = verdict.includes('WARN');
    $('strip').hidden = false;
    $('stripFlag').className = 'flag ' + (bad ? 'fail' : 'pass');
    $('stripFlag').textContent = bad ? 'Fails' : warn ? 'Passes' : 'Passes';
    $('stripWhat').textContent = bad
      ? (part.problems || [])[0] || 'check the report'
      : warn ? ((part.warnings || [])[0] || 'with notes') : 'every check';
  } else {
    $('strip').hidden = true;
  }

  const base = '/api/part/' + encodeURIComponent(part.name);
  $('dlStl').href = base + '/stl';
  $('dlStl').setAttribute('download', part.name + '.stl');
  for (const [id, ext] of [['dlStep', 'step'], ['dl3mf', '3mf']]) {
    const el = $(id);
    el.href = base + '/file/' + ext;
    el.setAttribute('download', part.name + '.' + ext);
    el.hidden = !(part.files || []).includes(ext);
  }

  // THE 3D VIEW IS OFFERED, NOT LOADED. The mesh is megabytes and most looks
  // at a part are answered by the turntable, so the iframe gets no src until
  // somebody asks for it - and it is reset here so the previous part's mesh is
  // never left on screen beside this part's numbers.
  show3d(false);
  $('viewToggle').hidden = false;

  $('reportText').textContent = part.report_md || '';
  $('reportBox').hidden = !part.report_md;
  $('specText').textContent = part.spec ? JSON.stringify(part.spec, null, 2) : '';
  $('specBox').hidden = !part.spec;

  loadFrames(part.name, part.frames || 24);
}

/* THE 3D VIEW.
 *
 * An iframe of /static/viewer.html - the SAME page the phone loads in its
 * WebView, rather than a second renderer written for the browser. Two
 * renderers is how the two clients end up showing a part slightly
 * differently, and the whole reason the page is served instead of bundled.
 *
 * The turntable stays loaded underneath. Toggling back is instant, and a
 * viewer that fails leaves the pictures rather than an empty plate. */
function show3d(on) {
  const frame = $('view3d');
  const toggle = $('viewToggle');
  const name = state.part?.name;

  toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
  toggle.textContent = on ? 'Turntable' : '3D';
  toggle.title = on
    ? 'Back to the rendered turntable'
    : 'Turn the actual mesh, drawn by this machine\u2019s GPU';

  if (!on || !name) {
    frame.hidden = true;
    // Dropped rather than hidden: an iframe left with a src keeps a WebGL
    // context and a megabyte of mesh alive behind a hidden element, and
    // browsers cap how many contexts a page may hold.
    frame.removeAttribute('src');
    $('frame').hidden = !name;
    return;
  }

  frame.src = '/static/viewer.html?part=' + encodeURIComponent(name);
  frame.hidden = false;
}

/* 11.7: say what the wait is. `null` clears it. */
function staging(message, failed) {
  const box = $('staging');
  box.hidden = !message;
  box.classList.toggle('failed', !!failed);
  $('stagingText').textContent = message || '';
}

/* 11.6: the ONE orchestrated moment. Applied to the first frame only — a
   re-render on every drag step would be motion sickness. */
function loadFrames(name, count) {
  state.frameCount = count;
  state.frames = new Array(count);
  const url = (i) => frameUrl(name, i, 760);
  const start = Math.round(count / 8) % count;
  state.step = start;

  // THE OLD PICTURE GOES FIRST. The facts, the volume and the download links
  // are already this part's; leaving the previous part's render up beside them
  // shows one part's numbers under another part's picture, which on a
  // measuring instrument is the worst failure in the file.
  $('frame').hidden = true;
  staging('Rendering the part - the first view takes a few seconds.');

  const first = new Image();
  first.onload = () => {
    state.frames[start] = first;
    const frame = $('frame');
    frame.hidden = false;
    frame.src = first.src;
    frame.classList.remove('resolving');
    void frame.offsetWidth;
    frame.classList.add('resolving');
    $('blank').hidden = true;
    staging(null);

    const order = [];
    for (let d = 1; d <= count; d++) {
      order.push((start + d) % count);
      order.push((start - d + count) % count);
    }
    const wanted = order.filter((i, k) => order.indexOf(i) === k && i !== start);
    let next = 0;
    const pump = () => {
      if (next >= wanted.length || state.part?.name !== name) return;
      const i = wanted[next++];
      const img = new Image();
      img.onload = img.onerror = () => { state.frames[i] = img.complete ? img : null; pump(); };
      img.src = url(i);
    };
    pump();
  };
  // A render that fails SAYS SO. It used to hide the frame and leave a bare
  // build plate, which looks exactly like a part that has not arrived yet.
  first.onerror = () => {
    $('frame').hidden = true;
    staging('Could not render this part. The geometry and the downloads '
            + 'below are unaffected.', true);
  };
  first.src = url(start);
}

function spinTo(step) {
  const count = state.frameCount;
  let i = ((step % count) + count) % count;
  for (let d = 0; d < count; d++) {
    const c = (i - d + count * 2) % count;
    if (state.frames[c]) { i = c; break; }
  }
  if (state.frames[i]) {
    state.step = i;
    const frame = $('frame');
    frame.classList.remove('resolving');
    frame.src = state.frames[i].src;
  }
}

function wireStage() {
  const stage = $('stage');
  let dragging = false, lastX = 0, startStep = 0;

  stage.addEventListener('pointerdown', (e) => {
    if ($('frame').hidden) return;
    dragging = true; lastX = e.clientX; startStep = state.step;
    interacting(true);                       // 11.5.4
    stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const perStep = Math.max(6, stage.clientWidth / state.frameCount);
    spinTo(startStep - Math.round((e.clientX - lastX) / perStep));
  });
  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    interacting(false);
    try { stage.releasePointerCapture(e.pointerId); } catch {}
  };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);
}

/* ── library ─────────────────────────────────────────────────────────── */

async function loadLibrary() {
  try {
    const { parts } = await api('/api/parts');
    state.library = parts || [];
    const host = $('library');
    host.innerHTML = '';
    if (!state.library.length) {
      host.innerHTML = '<p class="empty">Nothing here yet.</p>';
      return;
    }
    state.library.forEach((p) => {
      const card = document.createElement('button');
      card.className = 'opt'; card.type = 'button';
      const img = document.createElement('img');
      img.loading = 'lazy'; img.alt = p.name;
      if (p.built) img.src = frameUrl(p.name, 3, 280);
      const nm = document.createElement('div');
      nm.className = 'nm'; nm.textContent = p.name;
      const mm = document.createElement('div');
      mm.className = 'mm';
      if (p.size_mm) mm.textContent = p.size_mm.map((v) => Math.round(v)).join(' × ') + ' mm';
      card.append(img, nm, mm);
      card.addEventListener('click', () => openPart(p.name));
      host.appendChild(card);
    });
  } catch {
    $('library').innerHTML = '<p class="empty">Could not read the library.</p>';
  }
}

async function openPart(name) {
  try {
    const data = await api('/api/part/' + encodeURIComponent(name));
    showPart({
      name,
      verdict: '',                       // not stored; re-verifying costs a rebuild
      report_md: data.report_md || '',
      spec: data.spec || null,
      frames: data.frames || 24,
      size_mm: data.size_mm || null,
      volume_cm3: data.volume_cm3 ?? null,
      // PIECES. showPart has always rendered this; openPart listed the fields
      // it forwards and this was not among them, so a part opened from the
      // library - the only way you ever look at one again - never showed how
      // many bodies it has. On anything with a moving part that is the fact
      // that decides whether it works: two bodies turn, one is fused solid.
      bodies: data.bodies ?? null,
      material: data.material || null,
      files: data.files || [],
    });
  } catch (err) {
    log('could not open ' + name + ': ' + err.message);
  }
}

/* ── wiring ──────────────────────────────────────────────────────────── */

$('generate').addEventListener('click', generate);
$('refineBtn').addEventListener('click', refine);
$('moreExports').addEventListener('click', () => {
  const row = $('exportRow');
  row.hidden = !row.hidden;
});
$('viewToggle').addEventListener('click', () => {
  show3d($('viewToggle').getAttribute('aria-pressed') !== 'true');
});
$('strip').addEventListener('click', () => {
  const box = $('reportBox');
  box.open = !box.open;
  $('strip').setAttribute('aria-expanded', String(box.open));
  if (box.open) box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});
document.querySelectorAll('.seed').forEach((seed) => {
  seed.addEventListener('click', () => {
    $('prompt').value = seed.dataset.fill;
    $('prompt').focus();
  });
});
// 11.5.7: a manual escape for low-end devices, remembered.
$('flatToggle').addEventListener('click', () => {
  const flat = document.body.classList.toggle('flat');
  $('flatToggle').textContent = flat ? 'Restore effects' : 'Reduce effects';
  try { localStorage.setItem('bpcad-flat', flat ? '1' : ''); } catch {}
});
try {
  if (localStorage.getItem('bpcad-flat')) {
    document.body.classList.add('flat');
    $('flatToggle').textContent = 'Restore effects';
  }
} catch {}

$('prompt').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !matchMedia('(max-width: 560px)').matches) {
    e.preventDefault(); generate();
  }
});
$('refine').addEventListener('keydown', (e) => { if (e.key === 'Enter') refine(); });

/* Installable. Fails silently — a browser that refuses to register a worker
   must still get a working app rather than a console error. */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js', { scope: '/' }).catch(() => {});
  });
}

wireStage();
boot();
