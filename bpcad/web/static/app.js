/*
 * bpcad web client.
 *
 * No framework and no build step. The whole surface is one prompt, one
 * turntable, one refine box and a list, and a framework to hold that would be
 * more code than the thing it holds - plus a build step, which is one more way
 * for the app to be broken on a machine with no internet.
 *
 * THE TURNTABLE PRELOADS. Dragging through frames that are still being
 * rendered gives a viewer that stutters and feels broken, when in fact it is
 * working perfectly and merely waiting. So the frames are fetched in the
 * background after the first one paints, nearest-angle-first, and dragging
 * only ever shows a frame that has already arrived.
 */

'use strict';

const $ = (id) => document.getElementById(id);

/*
 * STAGES, NOT A PERCENTAGE.
 *
 * The engine cannot say how far through it is - a model call takes as long as
 * it takes - so a percentage would be invented. These are the real stages it
 * reports, and the bar steps when one completes and then waits. It idles
 * visibly rather than creeping towards 99% and stopping, which is the lie
 * every progress bar tells.
 */
const STAGES = [
  { key: 'thinking',  match: /using|attempt|started/i,      at: 12 },
  { key: 'composing', match: /primitives|template|no templ/i, at: 34 },
  { key: 'building',  match: /building geometry/i,          at: 58 },
  { key: 'checking',  match: /verify|checking|export/i,     at: 74 },
  { key: 'options',   match: /building options/i,           at: 86 },
];

const state = {
  part: null,        // the part currently shown
  frames: [],        // preloaded Image objects, index = turntable step
  frameCount: 24,
  step: 0,
  job: null,
  started: 0,
  timer: null,
  stage: -1,
  options: [],
  capability: {},
};

/* ── helpers ─────────────────────────────────────────────────────────── */

async function api(path, options) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch { throw new Error('the server sent something that is not JSON: ' + text.slice(0, 120)); }
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}

function post(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

function stage(text) {
  for (let i = STAGES.length - 1; i >= 0; i--) {
    if (STAGES[i].match.test(text) && i > state.stage) {
      state.stage = i;
      $('workStage').textContent = STAGES[i].key;
      $('trackFill').style.width = STAGES[i].at + '%';
      return;
    }
  }
}

function log(text, cls) {
  stage(text);
  const el = $('log');
  const stamp = new Date().toTimeString().slice(0, 8);
  const line = document.createElement('div');
  line.innerHTML = '<span class="t">' + stamp + '</span>  ' +
                   '<span class="' + (cls || '') + '"></span>';
  line.lastChild.textContent = text;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function setBusy(button, busy, idleLabel) {
  button.disabled = busy;
  button.classList.toggle('busy', busy);
  button.querySelector('.label').textContent = busy ? 'Working' : idleLabel;
}

function verdictClass(v) {
  const s = (v || '').toUpperCase();
  if (s.startsWith('PASS') && !s.includes('WARN')) return 'pass';
  if (s.startsWith('FAIL')) return 'fail';
  return 'warn';
}

/* ── startup ─────────────────────────────────────────────────────────── */

async function boot() {
  try {
    const h = await api('/api/health');
    // SAY WHAT THE WAIT WILL BE, BEFORE ANYONE COMMITS TO IT.
    //
    // "model ready" is true and useless. On a machine with no GPU a prompt is
    // two and a half minutes, and someone who is not told that concludes the
    // app has hung. Someone who IS told decides whether to wait. The dot is
    // amber rather than red for CPU: it is slow, not broken, and every other
    // part of the program is unaffected.
    const cap = h.capability || {};
    const model = h.model || {};
    state.capability = cap;

    const tier = cap.tier || (model.ok === false ? 'no-model' : 'cpu');
    $('statusDot').className = 'dot ' + (
      tier === 'gpu' ? 'up' : tier === 'cpu' ? 'slow' : 'down');
    $('statusText').textContent =
      tier === 'gpu' ? (cap.gpu_name ? cap.gpu_name + ' · fast' : 'gpu · fast')
      : tier === 'cpu' ? 'cpu · ~' + Math.round((cap.prompt_seconds || 155) / 60) + ' min a prompt'
      : 'no model · specs still work';
    if (cap.headline) $('status').title = cap.headline;
    $('capNote').textContent = cap.headline || '';
    $('capNote').hidden = !cap.headline || tier === 'gpu';

    const sel = $('material');
    sel.innerHTML = '';
    (h.materials || ['petg']).forEach((m) => {
      const o = document.createElement('option');
      o.value = m; o.textContent = m;
      sel.appendChild(o);
    });

    const p = h.printer || {}, bed = h.bed || {};
    if (p.name) {
      const size = (bed.width_mm && bed.depth_mm && bed.height_mm)
        ? `${bed.width_mm} × ${bed.depth_mm} × ${bed.height_mm} mm`
        : '';
      $('printerHint').textContent = `${p.name}${size ? ' · ' + size : ''}` +
        (p.multi_colour ? ' · multi-colour' : '');
      $('footPrinter').textContent = p.name;
    }
  } catch (err) {
    $('statusDot').className = 'dot down';
    $('statusText').textContent = 'server not answering';
  }
  loadLibrary();
}

/* ── generating ──────────────────────────────────────────────────────── */

async function create() {
  const request = $('prompt').value.trim();
  if (!request) { $('prompt').focus(); return; }

  // Tell them the wait BEFORE the wait, not after.
  const seconds = (state.capability || {}).prompt_seconds;
  $('workEta').textContent = seconds
    ? (seconds > 90 ? 'about ' + Math.round(seconds / 60) + ' minutes on this machine'
                    : 'about ' + seconds + ' seconds')
    : '';

  setBusy($('createBtn'), true, 'Create');
  $('runPanel').hidden = false;
  $('log').innerHTML = '';
  $('workReq').textContent = request;
  $('workStage').textContent = 'thinking';
  $('trackFill').style.width = '6%';
  state.stage = -1;
  resetOptions();
  $('partPanel').hidden = true;
  $('statusDot').className = 'dot busy';
  $('statusText').textContent = 'working';
  startClock();
  log('> ' + request, 'a');

  try {
    const { job } = await post('/api/generate', {
      request, material: $('material').value,
    });
    follow(job, (result) => {
      setBusy($('createBtn'), false, 'Create');
      stopClock();
      $('trackFill').style.width = '100%';
      if (result && result.ok) {
        log('done — ' + result.name, 'g');
        $('workStage').textContent = 'done';
        showPart(result);
        loadLibrary();
      } else {
        $('workStage').textContent = 'failed';
        log((result && result.message) || 'no part produced', 'r');
      }
      $('statusDot').className = 'dot up';
      $('statusText').textContent = 'idle';
    });
  } catch (err) {
    setBusy($('createBtn'), false, 'Create');
    stopClock();
    log(err.message, 'r');
    $('statusDot').className = 'dot down';
  }
}

async function refine() {
  const instruction = $('refine').value.trim();
  if (!instruction || !state.part) return;

  setBusy($('refineBtn'), true, 'Apply');
  $('runPanel').hidden = false;
  startClock();
  log('> ' + instruction, 'a');

  try {
    const { job } = await post('/api/refine', {
      name: state.part.name, instruction,
    });
    follow(job, (result) => {
      setBusy($('refineBtn'), false, 'Apply');
      stopClock();
      if (result && result.ok) {
        (result.changes || []).forEach((c) => log('  ' + c, 'g'));
        log('done — ' + result.name, 'g');
        $('refine').value = '';
        showPart(result);
        loadLibrary();
      } else {
        log((result && result.message) || 'could not apply that', 'r');
      }
    });
  } catch (err) {
    setBusy($('refineBtn'), false, 'Apply');
    stopClock();
    log(err.message, 'r');
  }
}

/*
 * Follow a job over SSE.
 *
 * The stream replays everything that has already happened when it opens, so a
 * phone that locked its screen and dropped the connection comes back to the
 * whole log rather than joining halfway through with no idea what it missed.
 */
function follow(jobId, onDone) {
  const source = new EventSource('/api/job/' + jobId + '/events');
  state.job = source;
  let finished = false;

  source.onmessage = (message) => {
    let event;
    try { event = JSON.parse(message.data); } catch { return; }

    if (event.kind === 'option')      addOption(event);
    else if (event.kind === 'note')   log('  ' + event.text);
    else if (event.kind === 'started') log('  started');
    else if (event.kind === 'failed')  { finished = true; onDone(event); }
    else if (event.kind === 'done')    { finished = true; onDone(event); }
    else if (event.kind === 'closed') {
      source.close();
      state.job = null;
      if (!finished) onDone(null);
    }
  };

  // A dropped connection is not a failed job - the work carries on server
  // side. Ask once for the final state rather than declaring failure.
  source.onerror = () => {
    source.close();
    state.job = null;
    if (finished) return;
    api('/api/job/' + jobId)
      .then((j) => { if (j.done) onDone(j.result); else log('  connection dropped, work continues'); })
      .catch(() => log('  lost the connection', 'r'));
  };
}

function startClock() {
  state.started = Date.now();
  stopClock();
  state.timer = setInterval(() => {
    $('elapsed').textContent = Math.round((Date.now() - state.started) / 1000) + 's';
  }, 1000);
}
function stopClock() { if (state.timer) { clearInterval(state.timer); state.timer = null; } }

/* ── options ─────────────────────────────────────────────────────────────
 *
 * Cards appear as each option finishes building rather than all at once at the
 * end. Watching them land is the difference between "it is working" and "it
 * has hung", and it costs nothing - the server already emits each one.
 */

function resetOptions() {
  state.options = [];
  $('options').innerHTML = '';
  $('optionsPanel').hidden = true;
}

function addOption(option) {
  state.options.push(option);
  $('optionsPanel').hidden = false;

  const card = document.createElement('button');
  card.className = 'card option pending';
  card.type = 'button';

  const label = document.createElement('div');
  label.className = 'label';
  label.textContent = option.label || 'option';

  const img = document.createElement('img');
  img.className = 'thumb';
  // EAGER, not lazy. An option card is created because the user asked for it
  // and the panel is revealed in the same tick; a lazy image appended to a
  // container that was hidden a moment ago may never begin loading at all, so
  // onload never fires and the card sits in its loading shimmer for ever.
  // Four cached thumbnails stayed "pending" indefinitely on exactly this.
  img.loading = 'eager';
  img.decoding = 'async';
  img.alt = option.label || option.name;
  const settle = () => card.classList.remove('pending');
  img.onload = settle;
  img.onerror = settle;
  img.src = '/api/part/' + encodeURIComponent(option.name) + '/frame/3?w=340';
  // A cached image can finish before the handler is even reached.
  if (img.complete) settle();

  const size = document.createElement('div');
  size.className = 'sz';
  if (option.envelope_mm) {
    size.textContent = option.envelope_mm.map((v) => Math.round(v)).join(' × ') + ' mm';
  }
  const vol = document.createElement('div');
  vol.className = 'tp';
  if (option.volume_cm3 != null) vol.textContent = Math.round(option.volume_cm3) + ' cm³';

  card.append(label, img, size, vol);
  card.addEventListener('click', () => {
    document.querySelectorAll('.card.option').forEach((c) => c.classList.remove('chosen'));
    card.classList.add('chosen');
    openPart(option.name);
  });
  $('options').appendChild(card);

  $('optionsSub').textContent = state.options.length === 1
    ? 'Pick one. Every one of these builds and passes its checks.'
    : state.options.length + ' options. Every one builds and passes its checks.';
}

/* ── showing a part ──────────────────────────────────────────────────── */

function showPart(part) {
  state.part = part;
  state.frames = [];

  $('partPanel').hidden = false;
  $('partName').textContent = part.name;
  // A part opened from the library carries no verdict, because none is
  // stored and re-verifying costs as much as rebuilding. An empty badge is
  // hidden rather than shown blank - a blank badge reads as "no problems".
  const hasVerdict = Boolean(part.verdict);
  $('verdict').hidden = !hasVerdict;
  $('verdict').textContent = part.verdict || '';
  $('verdict').className = 'verdict ' + verdictClass(part.verdict);

  const bits = [];
  if (part.size_mm) bits.push(part.size_mm.map((v) => Math.round(v)).join(' × ') + ' mm');
  if (part.volume_cm3 != null) bits.push(part.volume_cm3 + ' cm³');
  if (part.bodies != null) bits.push(part.bodies === 1 ? 'one piece' : part.bodies + ' pieces');
  if (part.template) bits.push(part.template);
  else if (part.level === 2) bits.push('composed from primitives');
  if (part.material) bits.push(part.material);
  if (part.watertight === false) bits.push('NOT WATERTIGHT');
  $('partMeta').textContent = bits.join(' · ');

  const base = '/api/part/' + encodeURIComponent(part.name);
  $('dlStl').href = base + '/stl';
  $('dlStl').setAttribute('download', part.name + '.stl');
  for (const [id, ext] of [['dlStep', 'step'], ['dl3mf', '3mf']]) {
    const el = $(id);
    el.href = base + '/file/' + ext;
    el.setAttribute('download', part.name + '.' + ext);
    el.hidden = !(part.files || []).includes(ext);
  }

  const report = part.report_md || '';
  $('reportText').textContent = report;
  $('reportBox').hidden = !report;
  $('specText').textContent = part.spec ? JSON.stringify(part.spec, null, 2) : '';
  $('specBox').hidden = !part.spec;

  $('viewer').classList.remove('spun');
  loadFrames(part.name, part.frames || 24);
  $('partPanel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/*
 * Fetch the turntable.
 *
 * Frame 0 first and shown as soon as it lands, so there is a picture almost
 * immediately. The rest follow one at a time - the server renders these on a
 * CPU rasteriser and firing 24 requests at once would queue them all behind
 * each other AND make the first one slower.
 */
function loadFrames(name, count) {
  state.frameCount = count;
  state.frames = new Array(count);
  const url = (i) => '/api/part/' + encodeURIComponent(name) + '/frame/' + i + '?w=720';

  // Start on the three-quarter view, not straight on. Frame 0 looks at the
  // part square from the front, which for anything box-shaped is a grey
  // rectangle that says nothing about its shape - the birdhouse looked like a
  // door. An eighth of a turn is the angle every other render in this program
  // uses, for the same reason.
  const start = Math.round(count / 8) % count;
  state.step = start;

  const first = new Image();
  first.onload = () => {
    state.frames[start] = first;
    $('frame').src = first.src;
    // Outward from the frame being shown, so the angles you reach first by
    // dragging are the ones that arrive first.
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
  first.onerror = () => { $('frame').removeAttribute('src'); };
  first.src = url(start);
}

function spinTo(step) {
  const count = state.frameCount;
  let i = ((step % count) + count) % count;
  // Never show a frame that has not arrived - fall back to the nearest one
  // that has, so dragging stays smooth while the rest are still rendering.
  for (let d = 0; d < count; d++) {
    const c = (i - d + count * 2) % count;
    if (state.frames[c]) { i = c; break; }
  }
  if (state.frames[i]) {
    state.step = i;
    $('frame').src = state.frames[i].src;
  }
}

/* Pointer events cover mouse, touch and pen with one path. */
function wireViewer() {
  const viewer = $('viewer');
  let dragging = false, lastX = 0, startStep = 0, moved = 0;

  viewer.addEventListener('pointerdown', (e) => {
    dragging = true; lastX = e.clientX; startStep = state.step; moved = 0;
    viewer.setPointerCapture(e.pointerId);
  });
  viewer.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX;
    moved += Math.abs(dx);
    // One full turn per viewer width, which feels right on a phone and a mouse.
    const perStep = Math.max(6, viewer.clientWidth / state.frameCount);
    spinTo(startStep - Math.round((e.clientX - lastX) / perStep));
    if (moved > 8) viewer.classList.add('spun');
  });
  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    try { viewer.releasePointerCapture(e.pointerId); } catch {}
  };
  viewer.addEventListener('pointerup', end);
  viewer.addEventListener('pointercancel', end);
}

/* ── library ─────────────────────────────────────────────────────────── */

let libraryCache = [];

async function loadLibrary() {
  try {
    const { parts } = await api('/api/parts');
    libraryCache = parts || [];
    renderLibrary($('search').value.trim().toLowerCase());
  } catch {
    $('library').innerHTML = '<p class="empty">could not read the library</p>';
  }
}

function renderLibrary(query) {
  const host = $('library');
  const rows = !query ? libraryCache : libraryCache.filter((p) =>
    [p.name, p.template, p.prompt, (p.makes || []).join(' ')]
      .filter(Boolean).join(' ').toLowerCase().includes(query));

  if (!rows.length) {
    host.innerHTML = '<p class="empty">' +
      (query ? 'nothing matches "' + query + '"' : 'nothing here yet — make something') +
      '</p>';
    return;
  }

  host.innerHTML = '';
  rows.forEach((p) => {
    const card = document.createElement('button');
    card.className = 'card';
    card.type = 'button';

    const img = document.createElement('img');
    img.className = 'thumb';
    img.loading = 'lazy';
    img.alt = p.name;
    if (p.built) img.src = '/api/part/' + encodeURIComponent(p.name) + '/frame/3?w=300';

    const nm = document.createElement('div');
    nm.className = 'nm'; nm.textContent = p.name;

    card.appendChild(img);
    card.appendChild(nm);
    if (p.size_mm) {
      const sz = document.createElement('div');
      sz.className = 'sz';
      sz.textContent = p.size_mm.map((v) => Math.round(v)).join(' × ') + ' mm';
      card.appendChild(sz);
    }
    if (p.template) {
      const tp = document.createElement('div');
      tp.className = 'tp'; tp.textContent = p.template;
      card.appendChild(tp);
    }
    card.addEventListener('click', () => openPart(p.name));
    host.appendChild(card);
  });
}

async function openPart(name) {
  try {
    const data = await api('/api/part/' + encodeURIComponent(name));
    showPart({
      name,
      verdict: '',                       // not stored; see the server comment
      report_md: data.report_md || '',
      spec: data.spec || null,
      frames: data.frames || 24,
      size_mm: data.size_mm || null,
      volume_cm3: data.volume_cm3 ?? null,
      template: data.template || null,
      material: data.material || null,
      level: data.level ?? null,
      // The server reports which formats exist. Without passing it through,
      // the STEP and 3MF buttons stayed hidden on every part opened from the
      // library or from an option card - the files were there and unreachable.
      files: data.files || [],
    });
  } catch (err) {
    log('could not open ' + name + ': ' + err.message, 'r');
  }
}

/* ── wiring ──────────────────────────────────────────────────────────── */

$('createBtn').addEventListener('click', create);
document.querySelectorAll('.chip.suggest').forEach((chip) => {
  chip.addEventListener('click', () => {
    $('prompt').value = chip.dataset.fill;
    $('prompt').focus();
  });
});
$('toggleLog').addEventListener('click', () => {
  const el = $('log');
  el.hidden = !el.hidden;
  $('toggleLog').textContent = el.hidden ? 'log' : 'hide';
});
$('refineBtn').addEventListener('click', refine);
$('showReport').addEventListener('click', () => { $('reportBox').open = !$('reportBox').open; });
$('showSpec').addEventListener('click', () => { $('specBox').open = !$('specBox').open; });
$('search').addEventListener('input', (e) => renderLibrary(e.target.value.trim().toLowerCase()));

// Enter sends, shift-enter makes a new line. On a phone the on-screen return
// key inserts a newline as usual, because there is no shift to hold.
$('prompt').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !matchMedia('(max-width: 560px)').matches) {
    e.preventDefault(); create();
  }
});
$('refine').addEventListener('keydown', (e) => { if (e.key === 'Enter') refine(); });

/* ── installable ─────────────────────────────────────────────────────────
 *
 * Registered last and failing silently. A service worker is a convenience -
 * it makes the app open instantly and survive a dropped connection - and a
 * browser that refuses to register one (private window, no HTTPS, iOS being
 * iOS) must still get a working app rather than a console error and a blank
 * page.
 *
 * It is NOT registered off localhost-only builds where it would cache a shell
 * that is about to change under it; the server sends no-cache for the shell
 * precisely so an update lands, and the worker respects that by going to the
 * network first.
 */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js', { scope: '/' })
      .catch(() => { /* not installable here; the app works regardless */ });
  });
}

wireViewer();
boot();
