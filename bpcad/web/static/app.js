/*
 * bpcad web workspace. Design handoff task C1, product brief 6.3.
 *
 * No framework and no build step. The surface is three panels, a viewport and
 * a command line, and a framework to hold that would be more code than the
 * thing it holds - plus a build step, which is one more way for the app to be
 * broken on a machine with no internet.
 *
 * THREE RULES FROM THE HANDOFF LIVE IN HERE RATHER THAN IN THE CSS
 * ----------------------------------------------------------------
 * 1. The blur DROPS to a flat tint while the model is being dragged or a
 *    slider moved, and comes back on settle. That is a class on <body>
 *    toggled by the interaction handlers, because CSS cannot know when a drag
 *    starts.
 *
 * 2. A numeric value is an INPUT, not a readout. Every slider has a tappable
 *    field beside it. A maker knows the exact number and hunting for it with
 *    a thumb is an insult.
 *
 * 3. Never show a dimension the user was not shown being chosen. Parsed
 *    values and assumed values are drawn differently and the difference is
 *    legible without reading either - brief 4.5.
 *
 * WHAT THIS FILE WILL NOT DO
 * --------------------------
 * It will not invent a number to fill a panel. Several panels in the design
 * are fed by data this server does not produce yet - a credit balance, a
 * calibration record, a structured check list for a part that was built last
 * week. Where that is so, the panel says what is missing in words. A designed
 * panel filled with plausible placeholder figures is the single worst thing
 * this interface could do, because every number on screen is supposed to be
 * measured.
 */

'use strict';

const $ = (id) => document.getElementById(id);

/* The real stages the engine reports. The line steps when one completes and
   then waits, rather than creeping to 99% and lying. */
const STAGES = [
  { key: 'Parsed the description', match: /using|attempt|started/i },
  { key: 'Resolved standards',     match: /primitives|template|no templ/i },
  { key: 'Built the solid',        match: /building geometry/i },
  { key: 'Ran your printer checks', match: /verify|checking|export/i },
  { key: 'Built the options',      match: /building options/i },
];

const state = {
  part: null,            // the part on screen, as the server described it
  frames: [], frameCount: 24, step: 0,
  job: null, started: 0, timer: null, stage: -1,
  capability: {}, printer: {}, bed: {}, library: [],
  renderVersion: 1, meshVersion: 1,
  photo: null,           // { path, url } once one is uploaded
  template: null,        // the schema behind the sliders, when there is one
  edits: {},             // slider changes not yet rebuilt
  history: [], cursor: 0,
  dims: false,
};

const frameUrl = (name, step, width) =>
  '/api/part/' + encodeURIComponent(name) + '/frame/' + step +
  '?w=' + width + '&rv=' + state.renderVersion;

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

/* Held for a moment after the last event so a stuttering drag does not flick
   the blur on and off, which is worse than either state. */
let settleTimer = null;
function interacting(on) {
  clearTimeout(settleTimer);
  if (on) { document.body.classList.add('interacting'); return; }
  settleTimer = setTimeout(
    () => document.body.classList.remove('interacting'), 180);
}

/* THE SCROLLBACK. Input in `screen`, success in the pass pen, anything
   provisional in amber - the design's three tones and the only colour in the
   panel. `tone` is one of said / ok / prov / bad. */
function say(text, tone) {
  const host = $('scrollback');
  const line = document.createElement('div');
  line.className = 'line' + (tone ? ' ' + tone : '');
  line.textContent = text;
  host.appendChild(line);
  host.scrollTop = host.scrollHeight;

  for (let i = STAGES.length - 1; i >= 0; i--) {
    if (STAGES[i].match.test(text) && i > state.stage) {
      state.stage = i;
      break;
    }
  }
}

const fmt = (value, places) =>
  Number(value).toFixed(places === undefined ? 1 : places);

/* ── startup ─────────────────────────────────────────────────────────── */

async function boot() {
  try {
    const health = await api('/api/health');
    const cap = health.capability || {};
    state.capability = cap;
    state.printer = health.printer || {};
    state.bed = health.bed || {};
    // See RENDER_VERSION and MESH_VERSION in web/server.py: an immutable
    // cache plus a versioned URL means a renderer change never reaches
    // anybody without it.
    state.renderVersion = health.render_version || 1;
    state.meshVersion = health.mesh_version || 1;

    const tier = cap.tier || 'cpu';
    $('lamp').className = 'lamp ' + (
      tier === 'gpu' ? 'ready' : tier === 'cpu' ? 'slow' : 'none');
    $('machineText').textContent =
      tier === 'gpu' ? (cap.gpu_name || 'GPU') + ' · fast'
      : tier === 'cpu' ? '~' + Math.round((cap.prompt_seconds || 155) / 60)
                         + ' min a part'
      : 'no model';
    $('lamp').title = cap.headline || '';

    // State the wait plainly. Someone who is not told concludes it hung.
    if (cap.headline && tier !== 'gpu') say(cap.headline, 'prov');

    const printer = state.printer, bed = state.bed;
    if (printer.name && bed.width_mm) {
      $('lamp').title += '  ·  ' + printer.name + ' ' + bed.width_mm + '×'
        + bed.depth_mm + '×' + bed.height_mm + ' mm';
      $('exportNote').textContent = 'Validated against ' + printer.name
        + ' · ' + (health.materials || ['petg'])[0].toUpperCase()
        + ' · ' + (health.print?.nozzle_mm || 0.4) + ' mm nozzle.';
    }
  } catch {
    $('lamp').className = 'lamp none';
    $('machineText').textContent = 'not answering';
    say('the server is not answering', 'bad');
  }
  loadLibrary();
}

/* ── generating ──────────────────────────────────────────────────────── */

async function generate(requestText) {
  const request = (requestText ?? $('prompt').value).trim();
  if (!request) { $('prompt').focus(); return; }

  $('generate').disabled = true;
  $('generate').textContent = 'Working';
  state.stage = -1;
  $('pipeline').hidden = true;
  staging(null);      // a stale "could not render" must not outlive the part

  const seconds = state.capability.prompt_seconds;
  say('> ' + request, 'said');
  if (seconds) {
    say(seconds > 90
      ? 'about ' + Math.round(seconds / 60) + ' minutes on this machine'
      : 'about ' + seconds + ' seconds', 'prov');
  }
  $('lamp').className = 'lamp busy';
  startClock();

  try {
    const body = { request, material: 'petg' };
    if (state.photo) body.image_path = state.photo.path;
    const { job } = await post('/api/generate', body);
    follow(job, finish);
  } catch (err) {
    say(err.message, 'bad');
    finish(null);
  }
}

function finish(result) {
  stopClock();
  $('generate').disabled = false;
  $('generate').textContent = 'Generate part';
  $('lamp').className = 'lamp ' +
    (state.capability.tier === 'gpu' ? 'ready' : 'slow');

  if (result && result.ok) {
    say('built ' + result.name, 'ok');
    showPart(result);
    loadLibrary();
  } else {
    say((result && result.message) || 'no part came out', 'bad');
  }
}

async function refine(instruction) {
  if (!instruction || !state.part) return;
  say('> ' + instruction, 'said');
  $('paramState').textContent = 'rebuilding…';
  $('paramState').className = 'state dirty';
  startClock();
  try {
    const { job } = await post('/api/refine',
      { name: state.part.name, instruction });
    follow(job, (result) => {
      stopClock();
      if (result && result.ok) {
        (result.changes || []).forEach((line) => say(line, 'ok'));
        state.edits = {};
        showPart(result);
        loadLibrary();
      } else {
        say((result && result.message) || 'could not apply that', 'bad');
        $('paramState').textContent = 'unchanged';
        $('paramState').className = 'state';
      }
    });
  } catch (err) {
    stopClock();
    say(err.message, 'bad');
    $('paramState').textContent = 'unchanged';
    $('paramState').className = 'state';
  }
}

/* The stream replays everything that already happened when it opens, so a
   tab that was asleep comes back to the whole story. */
function follow(jobId, onDone) {
  const source = new EventSource('/api/job/' + jobId + '/events');
  state.job = source;
  let finished = false;

  source.onmessage = (message) => {
    let event;
    try { event = JSON.parse(message.data); } catch { return; }

    if (event.kind === 'route') showPipeline(event);
    else if (event.kind === 'option') addOption(event);
    else if (event.kind === 'note') {
      // The router announces its decision as a note before any model call.
      // That is the pipeline banner's real source, and it is why the banner
      // stays hidden until it arrives rather than guessing.
      if (/no template fits|template/i.test(event.text || '')) {
        showPipeline({ text: event.text });
      }
      say(event.text, 'prov');
    }
    else if (event.kind === 'started') say('started', 'prov');
    else if (event.kind === 'failed' || event.kind === 'done') {
      finished = true; onDone(event);
    } else if (event.kind === 'closed') {
      source.close(); state.job = null;
      if (!finished) onDone(null);
    }
  };
  // A dropped connection is not a failed job - the work carries on server side.
  source.onerror = () => {
    source.close(); state.job = null;
    if (finished) return;
    api('/api/job/' + jobId)
      .then((j) => {
        if (j.done) onDone(j.result);
        else say('connection dropped, the work carries on', 'prov');
      })
      .catch(() => say('lost the connection', 'bad'));
  };
}

/* THE PIPELINE BANNER IS A TRUST SURFACE, so it says what the router actually
   decided and nothing more. The router runs before any model call and is
   deterministic, which is exactly what makes it safe to show before a credit
   is spent. */
function showPipeline(event) {
  const text = event.text || '';
  const template = /no template fits/i.test(text) ? null
    : (text.match(/template[: ]+([a-z_]+)/i) || [])[1] || null;

  $('pipelineHead').textContent = template
    ? 'Reading this as a ' + template.replace(/_/g, ' ')
    : 'Reading this as a functional part';
  $('pipelineBody').textContent = template
    ? 'A known shape with named parameters, so every number stays adjustable '
      + 'afterwards.'
    : 'Parametric solid, dimension-accurate, editable — composed from '
      + 'primitives rather than a template.';
  $('pipeline').hidden = false;
}

function startClock() {
  state.started = Date.now();
  stopClock();
  state.timer = setInterval(() => {
    $('readout').textContent =
      Math.round((Date.now() - state.started) / 1000) + 's';
  }, 1000);
}
function stopClock() {
  if (state.timer) { clearInterval(state.timer); state.timer = null; }
}

/* ── options, as a model switcher ────────────────────────────────────── */

function addOption(option) {
  const pill = document.createElement('button');
  pill.type = 'button';
  pill.className = 'pill glass glass--pill';
  pill.textContent = option.label || option.name;
  pill.addEventListener('click', () => {
    document.querySelectorAll('#switcher .pill')
      .forEach((p) => p.setAttribute('aria-pressed', 'false'));
    pill.setAttribute('aria-pressed', 'true');
    openPart(option.name);
  });
  $('switcher').appendChild(pill);
}

/* ── the part ────────────────────────────────────────────────────────── */

function showPart(part) {
  state.part = part;
  state.frames = [];
  state.edits = {};
  $('blank').hidden = true;

  // The name chip goes in the switcher, which is one wrapping flex row with
  // the toggles so a long name can never collide with them.
  $('switcher').innerHTML = '';
  const chip = document.createElement('div');
  chip.className = 'pill glass glass--pill name';
  const level = part.level === 1 ? 'parametric' : 'composed';
  chip.innerHTML = '<b></b> <span></span>';
  chip.querySelector('b').textContent = part.name;
  chip.querySelector('span').textContent = level;
  $('switcher').appendChild(chip);

  dimensionReport(part);
  checks(part);
  exports(part);
  parameters(part);
  versions(part);

  show3d(false);
  $('legend').hidden = false;
  $('hint').hidden = false;
  loadFrames(part.name, part.frames || 24);
}

/* THE DIMENSION REPORT. Measured, from the stored regression - the same
   numbers the library card shows, so the card and the panel cannot disagree.
   Nothing here is computed in the browser. */
function dimensionReport(part) {
  const host = $('dimReport');
  host.innerHTML = '';
  const row = (key, value, tone) => {
    const r = document.createElement('div');
    r.className = 'r';
    const k = document.createElement('div'); k.className = 'k'; k.textContent = key;
    const v = document.createElement('div');
    v.className = 'v num' + (tone ? ' ' + tone : ''); v.textContent = value;
    r.append(k, v); host.appendChild(r);
  };

  if (part.size_mm) {
    row('bounding box', part.size_mm.map((n) => fmt(n)).join(' × ') + ' mm');
  }
  if (part.volume_cm3 != null) row('volume', fmt(part.volume_cm3) + ' cm³');
  if (part.bodies != null) {
    // For anything with a moving part this is the fact that decides whether
    // it works: two bodies turn, one is fused solid.
    row('pieces', String(part.bodies), part.bodies === 1 ? '' : 'warn');
  }
  if (part.material) row('material', part.material);

  const bed = state.bed;
  if (part.size_mm && bed.width_mm) {
    const fits = part.size_mm[0] <= bed.width_mm
              && part.size_mm[1] <= bed.depth_mm
              && part.size_mm[2] <= bed.height_mm;
    row('bed fit', fits ? 'inside ' + bed.width_mm + ' mm' : 'over the bed',
        fits ? '' : 'warn');
  }
  $('reportPanel').hidden = !host.children.length;
}

/* CHECKS.
 *
 * A freshly built part carries a verdict, its problems and its warnings. A
 * part opened from the library does NOT - the server refuses to invent one,
 * because the only honest answers are to re-verify it (which costs as long as
 * building it) or to say nothing. So this panel says which of those two
 * situations you are in, rather than showing a row of green ticks that were
 * true last Tuesday.
 */
function checks(part) {
  const host = $('checks');
  host.innerHTML = '';

  const add = (tone, mark, name, tag, why) => {
    const el = document.createElement('div');
    el.className = 'check ' + tone;
    el.innerHTML = '<div class="cmark"></div><div class="cbody">'
      + '<div class="chead"><span class="cname"></span>'
      + '<span class="ctag"></span></div><p class="cwhy"></p></div>';
    el.querySelector('.cmark').textContent = mark;
    el.querySelector('.cname').textContent = name;
    el.querySelector('.ctag').textContent = tag;
    el.querySelector('.cwhy').textContent = why;
    host.appendChild(el);
  };

  const verdict = (part.verdict || '').toUpperCase();
  if (verdict) {
    const problems = part.problems || [];
    const warnings = part.warnings || [];
    if (!problems.length && !warnings.length) {
      add('pass', '✓', 'Every check', 'pass',
          'Watertight, inside the bed, and no wall under the nozzle width.');
    }
    problems.forEach((p) => add('fail', '✗', 'Failed', 'fail', p));
    warnings.forEach((w) => add('warn', '!', 'Warning', 'warn', w));
  } else {
    add('warn', '!', 'Not re-checked', 'unverified',
        'This part was verified when it was built and the result is in the '
        + 'report below. bpcad does not store a verdict, because re-checking '
        + 'costs as long as rebuilding and a remembered tick is not a check.');
  }

  $('reportText').textContent = part.report_md || '';
  $('reportBox').hidden = !part.report_md;
  $('checkPanel').hidden = false;
}

/* EXPORT. One row per format, with the size where it is known. A format this
   build cannot produce is absent rather than disabled: "you cannot have this"
   and "this is broken" must not look the same, and neither should "this part
   does not have one". */
function exports(part) {
  const host = $('exports');
  host.innerHTML = '';
  const base = '/api/part/' + encodeURIComponent(part.name);
  const have = part.files || [];

  const row = (ext, note, href, gated) => {
    const el = document.createElement(href ? 'a' : 'div');
    el.className = 'erow' + (gated ? ' gated' : '');
    if (href) { el.href = href; el.setAttribute('download', part.name + '.' + ext); }
    el.innerHTML = '<span class="etag"></span><div class="ebody">'
      + '<div class="ename"></div><p class="enote"></p></div>'
      + '<span class="esize num"></span>';
    el.querySelector('.etag').textContent = ext.toUpperCase();
    el.querySelector('.ename').textContent = part.name + '.' + ext;
    el.querySelector('.enote').textContent = note;
    el.querySelector('.esize').textContent = gated ? 'not built' : '';
    host.appendChild(el);
  };

  if (part.has_stl !== false) {
    row('stl', 'Repaired, oriented to a flat base', base + '/stl', false);
  }
  if (have.includes('3mf')) {
    row('3mf', 'With your printer profile embedded', base + '/file/3mf', false);
  }
  if (have.includes('step')) {
    row('step', 'Real solid geometry for CAD', base + '/file/step', false);
  } else {
    // Stated rather than hidden: STEP is a real capability of the exporter
    // and its absence here is about this part, not about the plan. The
    // design's Workshop gate is an entitlement question and there is no
    // account system to ask, so saying "gated" would be inventing one.
    row('step', 'Not written for this part', null, true);
  }

  $('dlStl').href = base + '/stl';
  $('dlStl').setAttribute('download', part.name + '.stl');
  $('exportPanel').hidden = false;
}

/* ── parameters ──────────────────────────────────────────────────────────
 *
 * SLIDERS ONLY WHERE THERE ARE REAL PARAMETERS, AND REAL BOUNDS.
 *
 * A level-1 part is a template plus named parameters, and the template's
 * schema carries each one's minimum, maximum, unit and description - so
 * /api/template/<name> is the only source of a range here. Inventing 1-80 for
 * a bore because the design shows 1-80 would be guessing at a dimension,
 * which is the one thing this project does not do.
 *
 * A level-2 part is a list of primitives. There is no "wall thickness" to
 * nudge in a list of ops, and a slider labelled "Wall" over a composition
 * would be a control that does nothing. So the panel says so, and points at
 * the two things that DO work on such a part: the command line and a change
 * asked for in words.
 */
async function parameters(part) {
  const host = $('params');
  host.innerHTML = '';
  state.template = null;
  $('paramNote').hidden = true;
  $('paramState').textContent = 'up to date';
  $('paramState').className = 'state';
  $('paramPanel').hidden = false;

  const params = part.spec?.params;
  if (!part.template || !params) {
    $('paramNote').textContent = part.level === 2
      ? 'Composed from primitives, so it has no named parameters. Ask for a '
        + 'change in words in the prompt, or use the command line.'
      : 'No parameters stored for this part.';
    $('paramNote').hidden = false;
    return;
  }

  let schema;
  try {
    schema = await api('/api/template/' + encodeURIComponent(part.template));
  } catch {
    $('paramNote').textContent = 'Could not read the ' + part.template
      + ' schema, so there are no bounds to slide between.';
    $('paramNote').hidden = false;
    return;
  }
  state.template = schema;

  const byName = {};
  (schema.params || []).forEach((p) => { byName[p.name] = p; });

  let shown = 0;
  for (const [name, value] of Object.entries(params)) {
    const spec = byName[name];
    // Only numbers get a slider. A boolean or an enum is a different control
    // and a fake slider over one is worse than no control.
    if (!spec || typeof value !== 'number') continue;
    const bounds = spec.bounds || {};
    const low = bounds.ge ?? bounds.gt;
    const high = bounds.le ?? bounds.lt;
    if (low === undefined || high === undefined) continue;

    host.appendChild(slider(name, spec, value, low, high));
    shown += 1;
  }

  if (!shown) {
    $('paramNote').textContent = 'The ' + part.template + ' template declares '
      + 'no numeric parameter with bounds, so there is nothing to slide.';
    $('paramNote').hidden = false;
    return;
  }

  const rebuild = document.createElement('button');
  rebuild.className = 'btn';
  rebuild.id = 'rebuild';
  rebuild.type = 'button';
  rebuild.disabled = true;
  rebuild.textContent = 'Rebuild';
  rebuild.addEventListener('click', () => {
    const changes = Object.entries(state.edits);
    if (!changes.length) return;
    // One sentence per change, through the same refine path the command line
    // uses - so a slider and `wall 3` cannot ask for different things.
    refine(changes.map(([name, v]) => {
      // The unit comes from the parameter's own name, not from an assumption
      // that everything is a length: `set n blades to 6 mm` is nonsense, and
      // it is the kind of nonsense a model will try to honour.
      const unit = name.endsWith('_mm') ? ' mm'
        : name.endsWith('_deg') ? ' degrees' : '';
      return 'set ' + name.replace(/_(mm|deg)$/, '').replace(/_/g, ' ')
        + ' to ' + v + unit;
    }).join(', '));
  });
  host.appendChild(rebuild);
}

function slider(name, spec, value, low, high) {
  const wrap = document.createElement('div');
  wrap.className = 'param';

  const label = name.replace(/_mm$/, '').replace(/_/g, ' ');

  // AN INTEGER PARAMETER IS AN INTEGER. The schema says which, and it has to
  // be honoured in three places at once - the step, the display and the value
  // sent back - or the blade count reads "4.0" and slides to 4.3, which is
  // not a louvre vent with four blades and a bit.
  const whole = spec.type === 'int';
  const step = whole ? 1 : (high - low) > 40 ? 0.5 : 0.1;
  const places = whole ? 0 : 1;
  const show = (v) => fmt(v, places);

  wrap.innerHTML =
    '<div class="prow"><span class="pname"></span>'
    + '<input class="pval num" type="text" inputmode="decimal">'
    + '<span class="punit"></span></div>'
    + '<input type="range">'
    + '<div class="pfoot"><span class="lo num"></span>'
    + '<span class="hintword"></span><span class="hi num"></span></div>';

  wrap.querySelector('.pname').textContent = label;
  wrap.querySelector('.punit').textContent = spec.units || '';
  wrap.querySelector('.hintword').textContent =
    (spec.description || '').replace(/\.$/, '').slice(0, 44);
  wrap.querySelector('.lo').textContent = show(low);
  wrap.querySelector('.hi').textContent = show(high);

  const range = wrap.querySelector('input[type="range"]');
  const field = wrap.querySelector('.pval');
  range.min = low; range.max = high; range.step = step; range.value = value;
  range.setAttribute('aria-label', label);
  field.value = show(value);

  const changed = (next) => {
    let clamped = Math.min(high, Math.max(low, Number(next)));
    if (!Number.isFinite(clamped)) return;
    if (whole) clamped = Math.round(clamped);
    range.value = clamped;
    field.value = show(clamped);
    state.edits[name] = Number(show(clamped));
    $('paramState').textContent = 'not rebuilt';
    $('paramState').className = 'state dirty';
    const rebuild = $('rebuild');
    if (rebuild) rebuild.disabled = false;
  };

  range.addEventListener('pointerdown', () => interacting(true));
  range.addEventListener('pointerup', () => interacting(false));
  range.addEventListener('input', () => changed(range.value));
  field.addEventListener('change', () => changed(field.value));
  field.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); changed(field.value); }
  });
  return wrap;
}

/* ── versions ────────────────────────────────────────────────────────────
 *
 * Grouped by the prompt that made them, which is real lineage the library
 * already carries - a refine writes a NEW part and keeps the old one, so
 * editing never destroys the last good result. There is no stored version
 * number, so the panel numbers them by build order and says nothing it cannot
 * support.
 */
function versions(part) {
  const prompt = part.prompt || '';
  const kin = prompt
    ? state.library.filter((p) => (p.prompt || '') === prompt)
    : [];

  const host = $('versions');
  host.innerHTML = '';
  if (kin.length < 2) { $('versionPanel').hidden = true; return; }

  kin.forEach((p, index) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'vrow';
    if (p.name === part.name) row.setAttribute('aria-current', 'true');
    row.innerHTML = '<span class="vid num"></span><span class="vnote"></span>'
      + '<span class="vdot"></span>';
    row.querySelector('.vid').textContent = 'v' + (index + 1);
    row.querySelector('.vnote').textContent = p.name;
    row.querySelector('.vdot').className = 'vdot ' + (p.built ? 'pass' : '');
    row.addEventListener('click', () => openPart(p.name));
    host.appendChild(row);
  });
  $('versionPanel').hidden = false;
}

/* ── the viewport ────────────────────────────────────────────────────── */

function staging(message, failed) {
  const box = $('staging');
  box.hidden = !message;
  box.classList.toggle('failed', !!failed);
  $('stagingText').textContent = message || '';
}

function loadFrames(name, count) {
  state.frameCount = count;
  state.frames = new Array(count);
  const url = (i) => frameUrl(name, i, 900);
  const start = Math.round(count / 8) % count;
  state.step = start;

  // THE OLD PICTURE GOES FIRST. The numbers beside it are already this part's;
  // leaving the previous part's render up shows one part's figures under
  // another part's picture, which on a measuring instrument is the worst
  // failure in the file.
  $('frame').hidden = true;
  staging('Rendering the part — the first view takes a few seconds.');

  const first = new Image();
  first.onload = () => {
    state.frames[start] = first;
    const frame = $('frame');
    frame.hidden = false;
    frame.src = first.src;
    frame.classList.remove('resolving');
    void frame.offsetWidth;
    frame.classList.add('resolving');
    staging(null);
    drawCallouts();

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
      img.onload = img.onerror = () => {
        state.frames[i] = img.complete ? img : null; pump();
      };
      img.src = url(i);
    };
    pump();
  };
  // A render that fails SAYS SO. It used to hide the frame and leave a bare
  // build plate, which looks exactly like a part that has not arrived yet.
  first.onerror = () => {
    $('frame').hidden = true;
    staging('Could not render this part. The geometry and the downloads are '
            + 'unaffected.', true);
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

/* DIMENSION CALLOUTS.
 *
 * The design projects these from 3D anchor points. The turntable is rendered
 * server-side and the browser is handed a picture, not a scene - so there are
 * no anchors to project from, and pretending otherwise would put a number
 * next to an edge it does not describe.
 *
 * What is honest and still useful: the measured bounding box, placed against
 * the three edges of the frame it corresponds to, labelled with the axis. The
 * numbers are the regression's own, to the tenth of a millimetre.
 */
function drawCallouts() {
  const host = $('callouts');
  host.innerHTML = '';
  const size = state.part?.size_mm;
  if (!state.dims || !size) { host.hidden = true; return; }

  const frame = $('frame');
  const box = frame.getBoundingClientRect();
  const stage = $('stage').getBoundingClientRect();
  if (!box.width) { host.hidden = true; return; }

  const left = box.left - stage.left;
  const top = box.top - stage.top;

  const place = (text, x, y) => {
    const chip = document.createElement('div');
    chip.className = 'callout num';
    chip.textContent = text;
    chip.style.left = x + 'px';
    chip.style.top = y + 'px';
    host.appendChild(chip);
  };

  place('X ' + fmt(size[0]) + ' mm', left + box.width / 2, top + box.height - 10);
  place('Y ' + fmt(size[1]) + ' mm', left + box.width - 46, top + box.height / 2);
  place('Z ' + fmt(size[2]) + ' mm', left + 40, top + box.height / 2);
  host.hidden = false;
}

function show3d(on) {
  const frame = $('view3d');
  const toggle = $('viewToggle');
  const name = state.part?.name;

  toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
  toggle.textContent = on ? 'turntable' : '3D';

  if (!on || !name) {
    frame.hidden = true;
    // Dropped rather than hidden: an iframe left with a src keeps a WebGL
    // context and a megabyte of mesh alive behind a hidden element, and
    // browsers cap how many contexts a page may hold.
    frame.removeAttribute('src');
    $('frame').hidden = !name;
    $('hint').textContent = 'drag to turn';
    drawCallouts();
    return;
  }

  frame.src = '/static/viewer.html?part=' + encodeURIComponent(name);
  frame.hidden = false;
  $('frame').hidden = true;
  $('callouts').hidden = true;
  $('hint').textContent = 'drag to orbit · scroll to zoom';
}

function wireStage() {
  const stage = $('stage');
  let dragging = false, lastX = 0, startStep = 0;

  stage.addEventListener('pointerdown', (e) => {
    if ($('frame').hidden) return;
    dragging = true; lastX = e.clientX; startStep = state.step;
    interacting(true);
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
  addEventListener('resize', drawCallouts);
}

/* ── library ─────────────────────────────────────────────────────────── */

async function loadLibrary() {
  try {
    const { parts } = await api('/api/parts');
    state.library = parts || [];
    const host = $('library');
    host.innerHTML = '';
    if (!state.library.length) {
      host.innerHTML = '<p class="empty">Nothing here yet. Describe a part '
        + 'and it lands in this panel.</p>';
      return;
    }
    state.library.forEach((p) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'card' + (p.built ? '' : ' draft');
      if (state.part && p.name === state.part.name) {
        card.setAttribute('aria-current', 'true');
      }

      const shot = document.createElement('div');
      shot.className = 'shot';
      if (p.built) {
        const img = document.createElement('img');
        img.loading = 'lazy'; img.alt = p.name;
        img.src = frameUrl(p.name, 3, 320);
        shot.appendChild(img);
      } else {
        shot.textContent = 'draft\nnot built';
      }

      const kind = document.createElement('div');
      kind.className = 'kind';
      kind.textContent = p.makes || (p.level === 1 ? 'parametric' : 'composed');

      const nm = document.createElement('div');
      nm.className = 'nm'; nm.textContent = p.name;

      const mm = document.createElement('div');
      mm.className = 'mm num';
      mm.textContent = p.size_mm
        ? p.size_mm.map((v) => Math.round(v)).join(' × ') + ' mm'
        : 'not built yet';

      card.append(shot, kind, nm, mm);
      card.addEventListener('click', () => openPart(p.name));
      host.appendChild(card);
    });
  } catch {
    $('library').innerHTML =
      '<p class="empty">Could not read the library.</p>';
  }
}

async function openPart(name) {
  try {
    const data = await api('/api/part/' + encodeURIComponent(name));
    const entry = state.library.find((p) => p.name === name) || {};
    showPart({
      name,
      verdict: '',          // not stored; re-verifying costs a rebuild
      report_md: data.report_md || '',
      spec: data.spec || null,
      level: data.level ?? null,
      template: data.template || null,
      frames: data.frames || 24,
      size_mm: data.size_mm || null,
      volume_cm3: data.volume_cm3 ?? null,
      bodies: data.bodies ?? null,
      material: data.material || null,
      files: data.files || [],
      has_stl: data.has_stl !== false,
      prompt: entry.prompt || '',
    });
    loadLibrary();
  } catch (err) {
    say('could not open ' + name + ': ' + err.message, 'bad');
  }
}

/* ── photos ──────────────────────────────────────────────────────────── */

async function attach(file) {
  if (!file) return;
  say('uploading ' + file.name, 'prov');
  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'upload refused');

    state.photo = { path: data.path, url: URL.createObjectURL(file) };

    const tile = document.createElement('button');
    tile.type = 'button';
    tile.className = 'tile photo';
    tile.title = 'Remove this photo';
    const img = document.createElement('img');
    img.src = state.photo.url; img.alt = 'the attached photo';
    tile.appendChild(img);
    tile.addEventListener('click', () => {
      URL.revokeObjectURL(state.photo.url);
      state.photo = null;
      tile.remove();
      say('photo removed', 'prov');
    });
    $('tiles').prepend(tile);

    // THE PHOTO IS A REFERENCE BODY, NOT A PART. Said plainly and up front,
    // because the whole scaling contract depends on somebody knowing that no
    // photograph carries absolute size.
    say('photo attached — it becomes a reference body, measured and not '
        + 'printed', 'ok');
  } catch (err) {
    say(err.message, 'bad');
  }
}

/* ── the command line ────────────────────────────────────────────────────
 *
 * PARSED SERVER-SIDE, by the same vocabulary the panels use. Written here in
 * JavaScript it would have to be written again in Dart for the phone, and
 * then `wall 3` would mean one thing in the browser and another on the phone
 * - the same class of bug as a colour that differs between clients, except
 * this one changes geometry. See bpcad/agent/command.py.
 */
async function runCommand() {
  const input = $('command');
  const line = input.value.trim();
  if (!line) return;

  input.value = '';
  state.history.push(line);
  state.cursor = state.history.length;
  say('> ' + line, 'said');

  let parsed;
  try {
    parsed = await post('/api/command', { line, material: 'petg' });
  } catch (err) {
    say(err.message, 'bad');
    return;
  }

  if (parsed.echo) {
    say(parsed.echo, parsed.problem ? 'bad'
      : parsed.kind === 'set' || parsed.kind === 'holes' ? 'prov' : 'ok');
  }

  switch (parsed.kind) {
    case 'set':
    case 'holes':
      if (!state.part) {
        say('there is no part on screen to change', 'bad');
        return;
      }
      refine(parsed.refine);
      return;

    case 'prompt':
      $('prompt').value = parsed.text;
      generate(parsed.text);
      return;

    case 'motion':
      if (!state.part) { say('no part on screen', 'bad'); return; }
      // The joint sweep is a rendered turntable on this build, so `motion`
      // shows what exists: the part turning, and the piece count that says
      // whether anything CAN move. Claiming a sweep the renderer did not
      // produce would be the interface lying about geometry.
      say(state.part.bodies > 1
        ? state.part.bodies + ' pieces — they move relative to each other'
        : 'one fused body — nothing in this part moves',
        state.part.bodies > 1 ? 'ok' : 'prov');
      return;

    case 'help':
    case 'ask':
    case 'incomplete':
    case 'rejected':
    case 'unknown':
    case 'empty':
      return;
  }
}

/* ── wiring ──────────────────────────────────────────────────────────── */

$('generate').addEventListener('click', () => generate());
$('prompt').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
    e.preventDefault(); generate();
  }
});

$('command').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); runCommand(); return; }
  // Scrollback the user can page and re-run - brief 6.4.
  if (e.key === 'ArrowUp' && state.cursor > 0) {
    e.preventDefault();
    state.cursor -= 1;
    $('command').value = state.history[state.cursor] || '';
  }
  if (e.key === 'ArrowDown' && state.cursor < state.history.length) {
    e.preventDefault();
    state.cursor += 1;
    $('command').value = state.history[state.cursor] || '';
  }
});

$('viewToggle').addEventListener('click', () => {
  show3d($('viewToggle').getAttribute('aria-pressed') !== 'true');
});
$('dimsToggle').addEventListener('click', () => {
  state.dims = !state.dims;
  $('dimsToggle').setAttribute('aria-pressed', String(state.dims));
  drawCallouts();
});
$('flatToggle').addEventListener('click', () => {
  const flat = document.body.classList.toggle('flat');
  $('flatToggle').setAttribute('aria-pressed', String(!flat));
  try { localStorage.setItem('bpcad-flat', flat ? '1' : ''); } catch {}
});
try {
  // Off by default and remembered, per the design: the bloom is an effect a
  // low-end GPU should be able to refuse.
  if (localStorage.getItem('bpcad-flat')) document.body.classList.add('flat');
} catch {}
$('flatToggle').setAttribute('aria-pressed',
  String(!document.body.classList.contains('flat')));

$('pickFile').addEventListener('click', () => $('fileInput').click());
$('pickCamera').addEventListener('click', () => $('cameraInput').click());
$('fileInput').addEventListener('change', (e) => attach(e.target.files[0]));
$('cameraInput').addEventListener('change', (e) => attach(e.target.files[0]));

/* Installable. Fails silently - a browser that refuses to register a worker
   must still get a working app rather than a console error. */
if ('serviceWorker' in navigator) {
  addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js', { scope: '/' })
      .catch(() => {});
  });
}

wireStage();
boot();
