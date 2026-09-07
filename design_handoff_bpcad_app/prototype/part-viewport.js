import * as THREE from 'three';

const HEX = {
  case: 0x0b0f0d, bezel: 0x151b18, etch: 0x2a322d,
  solid: 0xdce3dc, penDim: 0x4a554e, ref: 0x35c6e8,
  phosphor: 0xffb000, pass: 0x5be37d, fail: 0xe8489b,
};

function faceMat(color = HEX.bezel) {
  return new THREE.MeshBasicMaterial({
    color, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });
}

function edged(geom, color = HEX.solid, faceColor = HEX.bezel, lw = 1) {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(geom, faceMat(faceColor)));
  g.add(new THREE.LineSegments(
    new THREE.EdgesGeometry(geom, 20),
    new THREE.LineBasicMaterial({ color, linewidth: lw })
  ));
  return g;
}

function holeRing(r, color = HEX.solid) {
  const pts = [];
  for (let i = 0; i <= 48; i++) {
    const a = (i / 48) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * r, 0, Math.sin(a) * r));
  }
  return new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color })
  );
}

function graticule() {
  const g = new THREE.Group();
  const grid = new THREE.GridHelper(180, 18, HEX.penDim, HEX.penDim);
  grid.material.opacity = 0.5;
  grid.material.transparent = true;
  g.add(grid);
  const ax = (dir, color) => {
    const l = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), dir]),
      new THREE.LineBasicMaterial({ color })
    );
    return l;
  };
  g.add(ax(new THREE.Vector3(34, 0, 0), HEX.phosphor));
  g.add(ax(new THREE.Vector3(0, 34, 0), HEX.phosphor));
  g.add(ax(new THREE.Vector3(0, 0, 34), HEX.phosphor));
  const o = new THREE.Mesh(
    new THREE.SphereGeometry(1.6, 10, 8),
    new THREE.MeshBasicMaterial({ color: HEX.phosphor })
  );
  g.add(o);
  return g;
}

/* ---- models: each returns { group, anchors:[{p,text,pen}], animate(t) } ---- */

function bracketModel() {
  const group = new THREE.Group();
  const base = edged(new THREE.BoxGeometry(64, 5, 44));
  base.position.set(0, 2.5, 0);
  group.add(base);
  const wall = edged(new THREE.BoxGeometry(5, 40, 44));
  wall.position.set(-29.5, 22.5, 0);
  group.add(wall);
  const gus = edged(new THREE.BoxGeometry(4, 26, 26));
  gus.position.set(-24, 14, 0);
  group.add(gus);
  [[-14, -13], [-14, 13], [18, -13], [18, 13]].forEach(([x, z]) => {
    const r1 = holeRing(2.2); r1.position.set(x, 5.15, z); group.add(r1);
    const r2 = holeRing(2.2); r2.position.set(x, -0.15, z); group.add(r2);
  });
  return {
    group,
    anchors: [
      { p: new THREE.Vector3(32, 2.5, 22), text: '64.0', pen: 'solid' },
      { p: new THREE.Vector3(-29.5, 44, 0), text: '42.5', pen: 'solid' },
      { p: new THREE.Vector3(-14, 5, -13), text: '⌀4.5 M4', pen: 'pass' },
    ],
    animate: null,
  };
}

function hingeModel() {
  const group = new THREE.Group();
  const leafA = edged(new THREE.BoxGeometry(38, 4, 46));
  leafA.position.set(-19, 0, 0);
  group.add(leafA);

  const pivot = new THREE.Group();
  group.add(pivot);
  const leafB = edged(new THREE.BoxGeometry(38, 4, 46));
  leafB.position.set(19, 0, 0);
  pivot.add(leafB);

  const knuckle = (z, h, parent, color) => {
    const k = edged(new THREE.CylinderGeometry(7, 7, h, 20, 1, true), color);
    k.rotation.x = Math.PI / 2;
    k.position.set(0, 0, z);
    parent.add(k);
  };
  [-18, 0, 18].forEach((z) => knuckle(z, 10, group));
  [-9, 9].forEach((z) => knuckle(z, 8, pivot));

  const pin = edged(new THREE.CylinderGeometry(2.6, 2.6, 50, 16), HEX.phosphor, HEX.case);
  pin.rotation.x = Math.PI / 2;
  group.add(pin);

  return {
    group,
    anchors: [
      { p: new THREE.Vector3(0, 8, 22), text: 'clearance 0.28', pen: 'pass' },
      { p: new THREE.Vector3(-30, 2, 0), text: 'leaf 38.0', pen: 'solid' },
    ],
    animate: (t) => {
      const a = (Math.sin(t * 0.9) * 0.5 + 0.5) * (Math.PI * 0.55);
      pivot.rotation.z = -a;
    },
  };
}

function refFitModel() {
  const group = new THREE.Group();
  // reference body from photo — cyan, never printed
  const ref = new THREE.Group();
  const body = edged(new THREE.CylinderGeometry(16, 16, 54, 28, 1, true), HEX.ref, HEX.case);
  body.rotation.z = Math.PI / 2;
  body.position.set(0, 20, 0);
  ref.add(body);
  ref.traverse((o) => {
    if (o.material) { o.material.transparent = true; o.material.opacity = 0.55; }
  });
  group.add(ref);
  // parametric cradle around it
  const cradle = new THREE.Group();
  const seg = 22;
  for (let i = 0; i <= seg; i++) {
    const a = Math.PI + (i / seg) * Math.PI;
    const r = 18.6;
    const x = Math.cos(a) * r, y = 20 + Math.sin(a) * r;
    const blk = edged(new THREE.BoxGeometry(1.9, 4, 40));
    blk.position.set(x, y, 0);
    blk.rotation.z = a + Math.PI / 2;
    cradle.add(blk);
  }
  const foot = edged(new THREE.BoxGeometry(52, 5, 40));
  foot.position.set(0, 2.5, 0);
  cradle.add(foot);
  group.add(cradle);
  return {
    group,
    anchors: [
      { p: new THREE.Vector3(0, 40, 0), text: '⌀32.0 measured', pen: 'ref' },
      { p: new THREE.Vector3(20, 6, 20), text: 'fit +0.30 sliding', pen: 'warn' },
    ],
    animate: null,
  };
}

const MODELS = { bracket: bracketModel, hinge: hingeModel, fit: refFitModel };
const PEN_CSS = {
  solid: '#DCE3DC', ref: '#35C6E8', pass: '#5BE37D', warn: '#FFB000', fail: '#E8489B',
};

class PartViewport extends HTMLElement {
  static get observedAttributes() { return ['model', 'motion', 'dims', 'autorotate', 'scanline', 'viewinset']; }

  connectedCallback() {
    if (this._built) return;
    this._built = true;
    this.style.display = 'block';
    this.style.position = 'absolute';
    this.style.inset = '0';
    this.style.width = '100%';
    this.style.height = '100%';
    this.style.overflow = 'hidden';
    this.style.touchAction = 'none';
    this.style.cursor = 'grab';

    this._overlay = document.createElement('div');
    Object.assign(this._overlay.style, {
      position: 'absolute', inset: '0', pointerEvents: 'none', zIndex: '2',
    });
    this.appendChild(this._overlay);

    this._scan = document.createElement('div');
    Object.assign(this._scan.style, {
      position: 'absolute', inset: '0', pointerEvents: 'none', zIndex: '3', opacity: '0',
      background: 'repeating-linear-gradient(180deg, rgba(220,227,220,.055) 0 1px, transparent 1px 3px)',
      transition: 'opacity .3s',
    });
    this.appendChild(this._scan);

    this._renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this._renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    Object.assign(this._renderer.domElement.style, {
      position: 'absolute', inset: '0', width: '100%', height: '100%', zIndex: '1',
    });
    this.appendChild(this._renderer.domElement);

    this._scene = new THREE.Scene();
    this._camera = new THREE.PerspectiveCamera(34, 1, 1, 2000);
    this._grat = graticule();
    this._scene.add(this._grat);

    this._theta = Math.PI * 0.28;
    this._phi = Math.PI * 0.33;
    this._dist = 210;
    this._target = new THREE.Vector3(0, 16, 0);
    this._t0 = performance.now();
    this._idle = 0;

    this._buildModel();
    this._bindInput();

    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(this);
    this._resize();
    this._loop = this._loop.bind(this);
    this._raf = requestAnimationFrame(this._loop);
    this.attributeChangedCallback('scanline');
  }

  disconnectedCallback() {
    cancelAnimationFrame(this._raf);
    this._ro?.disconnect();
    this._renderer?.dispose();
  }

  attributeChangedCallback(name) {
    if (!this._built) return;
    if (name === 'model') this._buildModel();
    if (name === 'viewinset') this._fit();
    if (name === 'scanline') {
      const on = this.getAttribute('scanline') === 'on';
      this._scan.style.opacity = on ? '1' : '0';
    }
    if (name === 'dims') this._syncLabels();
  }

  _buildModel() {
    if (this._m) this._scene.remove(this._m.group);
    const key = this.getAttribute('model') || 'bracket';
    this._m = (MODELS[key] || bracketModel)();
    this._scene.add(this._m.group);
    const box = new THREE.Box3().setFromObject(this._m.group);
    const sph = box.getBoundingSphere(new THREE.Sphere());
    this._radius = sph.radius * 1.18;
    this._center = sph.center.clone();
    this._t0 = performance.now();
    this._fit();
    this._syncLabels();
  }

  /* frame the model against whichever fov axis is tighter, inside the band
     left over above the bottom sheet */
  _fit() {
    if (!this._radius) return;
    const w = this.clientWidth || 1, h = this.clientHeight || 1;
    const inset = Math.min(parseFloat(this.getAttribute('viewinset')) || 0, h * 0.6);
    const band = Math.max(80, h - inset);
    const vFov = THREE.MathUtils.degToRad(34);
    const tanV = Math.tan(vFov / 2) * (band / h);
    const tanH = Math.tan(vFov / 2) * this._camera.aspect;
    const half = Math.atan(Math.min(tanV, tanH));
    this._dist = this._radius / Math.sin(half);
    this._distMax = this._dist * 1.9;
    this._distMin = this._dist * 0.45;
    const worldPerPx = (2 * this._dist * Math.tan(vFov / 2)) / h;
    this._target = this._center.clone();
    this._target.y -= (inset / 2) * worldPerPx;
  }

  _syncLabels() {
    this._overlay.innerHTML = '';
    this._labels = [];
    if (this.getAttribute('dims') !== 'on') return;
    this._m.anchors.forEach((a) => {
      const el = document.createElement('div');
      el.textContent = a.text;
      Object.assign(el.style, {
        position: 'absolute', transform: 'translate(-50%,-50%)', whiteSpace: 'nowrap',
        font: "500 10.5px/1 'IBM Plex Mono', ui-monospace, monospace",
        letterSpacing: '.02em', color: PEN_CSS[a.pen] || PEN_CSS.solid,
        background: 'rgba(11,15,13,.82)', border: '1px solid ' + (PEN_CSS[a.pen] || PEN_CSS.solid) + '55',
        padding: '3px 5px', borderRadius: '3px', fontVariantNumeric: 'tabular-nums',
      });
      this._overlay.appendChild(el);
      this._labels.push({ el, p: a.p });
    });
  }

  _bindInput() {
    let drag = null;
    this.addEventListener('pointerdown', (e) => {
      drag = { x: e.clientX, y: e.clientY };
      this.setPointerCapture(e.pointerId);
      this.style.cursor = 'grabbing';
      this._idle = 0;
    });
    this.addEventListener('pointermove', (e) => {
      if (!drag) return;
      this._theta -= (e.clientX - drag.x) * 0.008;
      this._phi = Math.max(0.12, Math.min(Math.PI - 0.12, this._phi - (e.clientY - drag.y) * 0.006));
      drag = { x: e.clientX, y: e.clientY };
      this._idle = 0;
    });
    const end = () => { drag = null; this.style.cursor = 'grab'; };
    this.addEventListener('pointerup', end);
    this.addEventListener('pointercancel', end);
    this.addEventListener('wheel', (e) => {
      e.preventDefault();
      const lo = this._distMin || 90, hi = this._distMax || 420;
      this._dist = Math.max(lo, Math.min(hi, this._dist + e.deltaY * (hi / 900)));
      this._idle = 0;
    }, { passive: false });
  }

  _resize() {
    const w = this.clientWidth || 1, h = this.clientHeight || 1;
    this._renderer.setSize(w, h, false);
    this._camera.aspect = w / h;
    this._camera.updateProjectionMatrix();
    this._fit();
  }

  _loop() {
    this._raf = requestAnimationFrame(this._loop);
    const now = performance.now();
    const t = (now - this._t0) / 1000;
    const dt = 1 / 60;
    this._idle += dt;

    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (this.getAttribute('autorotate') !== 'off' && this._idle > 2.5 && !reduce) {
      this._theta += 0.0032;
    }
    if (this._m.animate && this.getAttribute('motion') === 'on' && !reduce) this._m.animate(t);

    // entrance: parts draw in over 0.9s
    const intro = Math.min(1, t / 0.9);
    const ease = 1 - Math.pow(1 - intro, 3);
    this._m.group.scale.setScalar(0.92 + 0.08 * ease);
    this._m.group.traverse((o) => {
      if (o.material && o.material.opacity !== undefined) {
        if (o.userData._baseOp === undefined) o.userData._baseOp = o.material.opacity ?? 1;
        o.material.transparent = true;
        o.material.opacity = o.userData._baseOp * ease;
      }
    });
    this._grat.traverse((o) => {
      if (o.material) { o.material.transparent = true; o.material.opacity = 0.5 * ease; }
    });

    const sp = new THREE.Spherical(this._dist, this._phi, this._theta);
    this._camera.position.setFromSpherical(sp).add(this._target);
    this._camera.lookAt(this._target);
    this._renderer.render(this._scene, this._camera);

    if (this._labels?.length) {
      const w = this.clientWidth, h = this.clientHeight;
      this._labels.forEach(({ el, p }) => {
        const v = p.clone().project(this._camera);
        el.style.left = ((v.x * 0.5 + 0.5) * w) + 'px';
        el.style.top = ((-v.y * 0.5 + 0.5) * h) + 'px';
        el.style.opacity = intro > 0.85 ? '1' : '0';
      });
    }

    this.dispatchEvent(new CustomEvent('viewport-frame', {
      detail: { theta: this._theta, dist: this._dist },
    }));
  }
}

if (!customElements.get('part-viewport')) customElements.define('part-viewport', PartViewport);
