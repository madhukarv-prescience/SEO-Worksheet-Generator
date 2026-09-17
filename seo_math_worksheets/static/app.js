/* Bhanzu SEO Math Worksheets — front end.
   Plain JS, no build step. Nothing backend-shaped is ever rendered:
   no provider names, no record ids, no key prompts. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = {
  sources: [],
  framework: null,
  currentBatch: null,
  reviseTarget: null,
};

/* ── helpers ─────────────────────────────────────────────── */
function toast(msg, ms = 2600) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) throw new Error((body && body.detail) || 'Something went wrong.');
  return body;
}

function form(data) {
  const fd = new FormData();
  Object.entries(data).forEach(([k, v]) => fd.append(k, v));
  return { method: 'POST', body: fd };
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ── navigation ──────────────────────────────────────────── */
// Tabs and the step path are two ways into the same move, so both go
// through here — otherwise one updates and the other silently doesn't.
// Two navs now: the step path is the workflow (library -> create ->
// review), the top bar is standing reference (repository, approved).
// Only one of the two ever shows a selection, so a workflow view must
// clear the top bar and vice versa.
const WORKFLOW = ['library', 'create', 'review'];
const REFERENCE = ['repository', 'approved', 'setup'];

function goTo(view, { scroll = true } = {}) {
  $$('.tab').forEach(t => t.classList.toggle('on', t.dataset.view === view));
  $$('.step').forEach(t => t.classList.toggle('on', t.dataset.view === view));
  $$('.view').forEach(v => v.classList.toggle('on', v.id === 'view-' + view));
  // The step path is only meaningful inside the workflow; dim it when
  // the reader is off in a reference section.
  $('#steps').classList.toggle('inactive', !WORKFLOW.includes(view));

  if (view === 'review') loadBatches();
  if (view === 'create') fillSourceSelect();
  if (view === 'repository') loadRepository();
  if (view === 'approved') loadApproved();
  if (view === 'setup') loadSetup();
  if (scroll) window.scrollTo({ top: 0, behavior: 'smooth' });
}

$$('.tab, .step').forEach(el =>
  el.addEventListener('click', () => goTo(el.dataset.view)));

// Any button that just moves you along the path.
$$('[data-goto]').forEach(el =>
  el.addEventListener('click', () => goTo(el.dataset.goto)));

/* ── startup ─────────────────────────────────────────────── */
async function boot() {
  const status = await api('/api/status');
  state.framework = status.framework;
  state.modes = status.modes;
  state.gradeLabels = status.grades;
  state.verdicts = status.verdicts;

  $('#gradeSelect').innerHTML = Object.entries(status.grades)
    .map(([k, v]) => `<option value="${k}"${k === '3' ? ' selected' : ''}>${esc(v)}</option>`).join('');

  $('#difficultySelect').innerHTML = Object.entries(status.difficulties)
    .map(([k, v]) => `<option value="${k}"${k === 'core' ? ' selected' : ''}>${esc(v.label)}</option>`).join('');

  $('#varyOptions').innerHTML = Object.entries(state.framework.variation_dimensions)
    .map(([k, desc], i) => `<span class="chip${i === 0 ? ' on' : ''}" data-dim="${k}" title="${esc(desc)}">${esc(label(k))}</span>`)
    .join('');
  $$('#varyOptions .chip').forEach(c =>
    c.addEventListener('click', () => c.classList.toggle('on')));

  $('#modeOptions').innerHTML = Object.entries(status.modes)
    .map(([k, m], i) => `
      <label class="mode${i === 0 ? ' on' : ''}">
        <input type="checkbox" name="mode" value="${k}"${i === 0 ? ' checked' : ''}>
        <span class="mt">${esc(m.label)}</span>
        <span class="mb">${esc(m.blurb)}</span>
      </label>`).join('');
  $$('#modeOptions input[name=mode]').forEach(r =>
    r.addEventListener('change', () => {
      // At least one must stay on, or there's nothing to build.
      if (!$$('#modeOptions input[name=mode]').some(x => x.checked)) r.checked = true;
      $$('#modeOptions .mode').forEach(l =>
        l.classList.toggle('on', l.querySelector('input').checked));
    }));

  // Grade pickers, shared by the create form and the template uploader.
  const gradeOpts = Object.entries(status.grades)
    .map(([k, v]) => `<option value="${k}"${k === '3' ? ' selected' : ''}>${esc(v)}</option>`).join('');
  $('#templateGrade').innerHTML =
    '<option value="any">Any grade</option>' +
    Object.entries(status.grades).map(([k, v]) =>
      `<option value="${k}">${esc(v)}</option>`).join('');

  $('#closingGoal').innerHTML = Object.entries(status.closing_goals)
    .map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('');

  state.maxPerRun = status.max_sources_per_run;
  $('#allSources').addEventListener('change', e => {
    const on = e.target.checked;
    $('#sourceSelect').disabled = on;
    $('#sourceSelect').required = !on;
    $('#sourceWarning').hidden = on || !$('#sourceSelect').value ||
      state.sources.find(s => s.id === $('#sourceSelect').value)?.likely_has_questions !== false;
    $('#includeFlaggedRow').hidden = !on;
  });
  $('#sourceSelect').addEventListener('change', showSourceWarning);

  $('#toCreate').addEventListener('click', () => goTo('create'));
  $('#createToReview').addEventListener('click', () => goTo('review'));
  $('#jobToReview').addEventListener('click', () => goTo('review'));

  await loadTemplates();
  await loadLibrary();
  refreshCounts();
}

async function refreshCounts() {
  try {
    const [repo, appr] = await Promise.all([
      api('/api/repository'), api('/api/approved')]);
    $('#repoCount').textContent = repo.totals.sources || '';
    $('#approvedCount').textContent = appr.total || '';
  } catch { /* counters are decoration; never block on them */ }
}

function label(key) {
  return key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
}

/* ── repository ──────────────────────────────────────────── */
function stat(label, value, accent) {
  return `<div class="stat${accent ? ' accent' : ''}">
    <span class="statnum">${value}</span><span class="statlabel">${esc(label)}</span></div>`;
}

async function loadRepository() {
  const { items, totals } = await api('/api/repository');

  $('#repoStats').innerHTML =
    stat('worksheets in the repository', totals.sources) +
    stat('run at least once', totals.used) +
    stat('versions generated', totals.made) +
    stat('approved', totals.approved, true) +
    Object.entries(totals.by_origin).map(([k, v]) => stat(k.toLowerCase(), v)).join('');

  $('#repoList').innerHTML = items.length
    ? items.map(i => `
        <div class="row">
          <div class="main">
            <div class="nm">${esc(i.filename)}</div>
            <div class="sub">${esc(i.origin_detail || '')} · ${i.page_count || 0} page(s)
              · added ${esc((i.added_at || '').slice(0, 10))}
              ${i.likely_has_questions === false
                ? '<span class="flagnote">⚠ activity sheet, not a question set</span>' : ''}</div>
          </div>
          ${i.made ? `<span class="pill">${i.made} version(s)</span>` : '<span class="pill">not used yet</span>'}
          ${i.approved ? `<span class="pill ok">${i.approved} approved</span>` : ''}
          <button class="btn sm" data-repoview="${i.id}">View</button>
        </div>`).join('')
    : '<p class="muted">Nothing brought in yet. Start in the library.</p>';

  $$('#repoList [data-repoview]').forEach(b => b.addEventListener('click', () =>
    window.open(`/api/sources/${b.dataset.repoview}/file`, '_blank')));

  $('#repoCount').textContent = totals.sources || '';
}

/* ── approved ────────────────────────────────────────────── */
async function loadApproved() {
  const { items, total } = await api('/api/approved');

  const grades = {};
  items.forEach(i => (grades[i.grade] = (grades[i.grade] || 0) + 1));
  $('#approvedStats').innerHTML =
    stat('approved worksheets', total, true) +
    Object.entries(grades).sort((a, b) => a[0] - b[0])
      .map(([g, n]) => stat(state.gradeLabels[g] || ('Grade ' + g), n)).join('');

  $('#approvedList').innerHTML = items.length
    ? items.map(i => `
        <div class="row">
          <div class="main">
            <div class="nm">${esc(i.title)}</div>
            <div class="sub">from ${esc(i.source_filename)}
              · ${esc(state.gradeLabels[i.grade] || 'Grade ' + i.grade)}
              · ${esc(i.difficulty)}${i.skill ? ' · ' + esc(i.skill) : ''}</div>
          </div>
          <button class="btn sm" data-appview="${i.id}">Preview</button>
          <button class="btn sm" data-appdl="${i.id}">Download PDF</button>
        </div>`).join('')
    : '<p class="muted">Nothing approved yet. Approve worksheets in review and they collect here.</p>';

  $$('#approvedList [data-appview]').forEach(b => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'Preparing…';
    try {
      const r = await api(`/api/worksheets/${b.dataset.appview}/export`, { method: 'POST' });
      window.open(r.view_url, '_blank');
    } catch (e) { toast(e.message); }
    b.disabled = false; b.textContent = 'Preview';
  }));

  $$('#approvedList [data-appdl]').forEach(b => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'Preparing…';
    try {
      // Export first — the PDF is only written when a worksheet is exported.
      await api(`/api/worksheets/${b.dataset.appdl}/export`, { method: 'POST' });
      window.open(`/api/worksheets/${b.dataset.appdl}/pdf`, '_blank');
    } catch (e) { toast(e.message); }
    b.disabled = false; b.textContent = 'Download PDF';
  }));

  $('#approvedCount').textContent = total || '';
}

/* ── setup / API key status ──────────────────────────────── */
function providerCard(key, label, docsUrl, info, extraLine) {
  const on = info.configured;
  return `
    <div class="setupcard ${on ? 'on' : ''}">
      <div class="setupcardhead">
        <span class="setupdot ${on ? 'on' : ''}"></span>
        <strong>${esc(label)}</strong>
        ${info.active ? '<span class="pill ok">in use now</span>' : ''}
        ${on && !info.active ? '<span class="pill">configured, not active</span>' : ''}
        ${!on ? '<span class="pill warn">not set</span>' : ''}
      </div>
      ${extraLine ? `<div class="setupline">${extraLine}</div>` : ''}
      ${!on ? `<div class="setupline">Get a key: <a href="${docsUrl}" target="_blank" rel="noopener">${esc(docsUrl.replace('https://', ''))}</a></div>` : ''}
    </div>`;
}

async function loadSetup() {
  const s = await api('/api/setup');
  const tp = s.text_providers;

  const providerHTML =
    providerCard('groq', 'Groq (question writing)', 'https://console.groq.com/keys',
      tp.groq, tp.groq.configured ? `Model: <code>${esc(tp.groq.model)}</code>` : '') +
    providerCard('anthropic', 'Anthropic (question writing)', 'https://console.anthropic.com/settings/keys',
      tp.anthropic, tp.anthropic.configured ? `Model: <code>${esc(tp.anthropic.model)}</code>` : '') +
    providerCard('openai', 'OpenAI (question writing + images)', 'https://platform.openai.com/api-keys',
      tp.openai, tp.openai.configured ? `Model: <code>${esc(tp.openai.model)}</code>` : '');

  const canva = s.canva;
  const canvaHTML = `
    <div class="setupcard ${canva.configured ? 'on' : ''}">
      <div class="setupcardhead">
        <span class="setupdot ${canva.configured ? 'on' : ''}"></span>
        <strong>Canva (image fallback only)</strong>
        ${canva.configured ? '<span class="pill ok">configured</span>' : '<span class="pill warn">not set</span>'}
      </div>
      <div class="setupline">
        Client ID: ${canva.client_id_set ? '✓ set' : '— not set'} ·
        Client secret: ${canva.client_secret_set ? '✓ set' : '— not set'} ·
        Brand template: ${canva.brand_template_set ? '✓ set' : '— not set'}
      </div>
      <div class="setupline">${esc(s.canva_stub_note)}</div>
      <div class="setupline">Docs: <a href="https://www.canva.com/developers/" target="_blank" rel="noopener">canva.com/developers</a></div>
    </div>`;

  $('#setupContent').innerHTML = `
    <h2 class="sectiontitle">Question writing — first key found wins</h2>
    <p class="hint" style="margin-bottom:14px;">
      Order: Groq → Anthropic → OpenAI. If more than one is set, add
      <code>LLM_PROVIDER=openai</code> (or groq/anthropic) to <code>.env</code>
      to force a specific one.
    </p>
    <div class="setupgrid">${providerHTML}</div>

    <h2 class="sectiontitle">Pictures</h2>
    <div class="setupgrid">
      <div class="setupcard on">
        <div class="setupcardhead"><span class="setupdot on"></span>
          <strong>Drawn diagrams</strong><span class="pill ok">always on</span></div>
        <div class="setupline">Number lines, counters, ten-frames, arrays and bar models are rendered by Python from a structured spec — correct by construction, no key needed.</div>
      </div>
      <div class="setupcard ${s.openai_images_configured ? 'on' : ''}">
        <div class="setupcardhead"><span class="setupdot ${s.openai_images_configured ? 'on' : ''}"></span>
          <strong>Photo-real / decorative art</strong>
          ${s.openai_images_configured ? '<span class="pill ok">enabled via OpenAI key</span>' : '<span class="pill warn">needs an OpenAI key</span>'}</div>
        <div class="setupline">Never used where the maths must be exact — only for scene-setting artwork.</div>
      </div>
      ${canvaHTML}
    </div>

    <h2 class="sectiontitle">The validation gate</h2>
    <div class="setupcard on">
      <div class="setupline">Every generated worksheet passes through <code>app/validate.py</code> before it reaches Review:</div>
      <ol class="setuplist">
        <li><strong>Structural checks</strong> (free, instant) — missing answers, blank template stems, duplicate questions, numbers outside the grade's range, a picture that reveals its own answer, a blank or missing diagram.</li>
        <li><strong>Sense check</strong> (one API call) — does each question make sense, and is the stated answer actually correct.</li>
      </ol>
      <div class="setupline">Result is one of four verdicts shown on every worksheet card in Review: <strong>passed</strong>, <strong>images need redrawing</strong> (fixed automatically, questions untouched), <strong>needs another pass</strong>, or <strong>could not finish checking</strong> — the last is never treated as a silent pass.</div>
    </div>
  `;
}

/* ── templates ───────────────────────────────────────────── */
async function loadTemplates() {
  const { templates } = await api('/api/templates');
  state.templates = templates;

  $('#templateCount').textContent = templates.length ? `· ${templates.length}` : '';
  $('#templateList').innerHTML = templates.length
    ? templates.map(t => `
        <div class="row">
          <div class="main">
            <div class="nm">${esc(t.name)}</div>
            <div class="sub">${t.grade === null ? 'Any grade' : esc(state.gradeLabels[t.grade] || 'Grade ' + t.grade)}</div>
          </div>
          <button class="btn sm" data-tview="${t.id}">View</button>
          <button class="btn sm" data-tdel="${t.id}">Remove</button>
        </div>`).join('')
    : '<p class="muted small">No templates yet — worksheets use the Bhanzu house style.</p>';

  $$('#templateList [data-tview]').forEach(b => b.addEventListener('click', () =>
    window.open(`/api/templates/${b.dataset.tview}/file`, '_blank')));
  $$('#templateList [data-tdel]').forEach(b => b.addEventListener('click', async () => {
    await api('/api/templates/' + b.dataset.tdel, { method: 'DELETE' });
    toast('Template removed'); await loadTemplates();
  }));

  const sel = $('#templateSelect');
  if (sel) {
    const keep = sel.value;
    sel.innerHTML = '<option value="">Bhanzu house style</option>' +
      templates.map(t => `<option value="${t.id}">${esc(t.name)}${
        t.grade === null ? '' : ' — ' + esc(state.gradeLabels[t.grade] || 'Grade ' + t.grade)}</option>`).join('');
    if (keep) sel.value = keep;
  }
}

$('#templateForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = e.target.querySelector('button');
  const fd = new FormData();
  fd.append('file', e.target.file.files[0]);
  fd.append('grade', e.target.grade.value);
  btn.disabled = true; btn.textContent = 'Adding…';
  try {
    await api('/api/templates', { method: 'POST', body: fd });
    toast('Template added'); e.target.reset(); await loadTemplates();
  } catch (err) { toast(err.message, 5000); }
  btn.disabled = false; btn.textContent = 'Add template';
});

/* ── library ─────────────────────────────────────────────── */
async function loadLibrary() {
  const data = await api('/api/sources');
  state.sources = data.sources;

  $('#collections').innerHTML = data.collections.length
    ? data.collections.map(c => {
        const remaining = c.total - c.already_added;
        return `
        <div class="coll">
          <div class="collhead">
            <div class="nm">${esc(c.category.replace(/_/g, ' '))}</div>
            <div class="sub">${c.already_added} of ${c.total} in your library</div>
          </div>
          <div class="collact">
            <input type="number" min="1" max="${c.total}" value="10"
                   data-amt="${esc(c.category)}" aria-label="How many">
            <button class="btn sm" data-add="${esc(c.category)}"
                    ${remaining ? '' : 'disabled title="All of them are already in your library"'}>Add</button>
            <button class="btn sm" data-rm="${esc(c.category)}"
                    ${c.already_added ? '' : 'disabled title="None of these are in your library yet"'}>Remove</button>
          </div>
        </div>`; }).join('')
    : '<p class="muted">No fetched collections found.</p>';

  const amountFor = cat =>
    Math.max(1, parseInt($(`#collections [data-amt="${cat}"]`).value, 10) || 1);

  $$('#collections [data-add]').forEach(b => b.addEventListener('click', async () => {
    const cat = b.dataset.add;
    b.disabled = true; b.textContent = 'Adding…';
    try {
      const r = await api('/api/sources/from-collection',
        form({ category: cat, limit: amountFor(cat) }));
      toast(r.added.length
        ? `${r.added.length} worksheet(s) added`
        : 'Nothing new to add — they are all in your library already');
      await loadLibrary();
    } catch (e) { toast(e.message); b.disabled = false; b.textContent = 'Add'; }
  }));

  $$('#collections [data-rm]').forEach(b => b.addEventListener('click', async () => {
    const cat = b.dataset.rm;
    const n = amountFor(cat);
    if (!confirm(`Take ${n} worksheet(s) back out of your library?`)) return;
    b.disabled = true; b.textContent = 'Removing…';
    try {
      let r = await api('/api/sources/remove-from-collection',
        form({ category: cat, count: n }));
      if (r.kept_back) {
        const msg = `${r.removed} removed. ${r.kept_back} more have worksheets ` +
                     `made from them — remove those too?`;
        if (confirm(msg)) {
          const extra = await api('/api/sources/remove-from-collection',
            form({ category: cat, count: r.kept_back, cascade: 'true' }));
          r = { removed: r.removed + extra.removed };
        }
      }
      toast(`${r.removed} worksheet(s) removed`);
      await loadLibrary(); await loadBatches();
    } catch (e) { toast(e.message); b.disabled = false; b.textContent = 'Remove'; }
  }));

  $('#sourceCount').textContent = state.sources.length ? `· ${state.sources.length}` : '';
  const n = state.sources.length, cap = state.maxPerRun || 25;
  const el = $('#allSourcesCount');
  if (el) el.textContent = !n ? '' :
    (n > cap ? `— ${cap} of ${n} per run` : `— ${n} of them`);
  $('#sourceList').innerHTML = state.sources.length
    ? state.sources.map(s => `
        <div class="row">
          <div class="main">
            <div class="nm">${esc(s.filename)}</div>
            <div class="sub">${esc(s.origin_detail || '')} · ${s.page_count || 0} page(s)
              ${s.likely_has_questions === false
                ? '<span class="flagnote">⚠ looks like an activity sheet, not a question set — may not generate well</span>'
                : ''}</div>
          </div>
          <span class="pill">${esc(s.origin_label)}</span>
          <button class="btn sm" data-view="${s.id}">View</button>
          <button class="btn sm" data-del="${s.id}">Remove</button>
        </div>`).join('')
    : '<p class="muted">Nothing added yet.</p>';

  $$('#sourceList [data-view]').forEach(b => b.addEventListener('click', () =>
    window.open(`/api/sources/${b.dataset.view}/file`, '_blank')));

  $$('#sourceList [data-del]').forEach(b => b.addEventListener('click', async () => {
    const id = b.dataset.del;
    try {
      await api('/api/sources/' + id, { method: 'DELETE' });
      toast('Removed');
    } catch (e) {
      // The source has generated worksheets hanging off it. That's a
      // decision, not an error — ask rather than refusing or silently
      // destroying the work.
      if (!confirm(`${e.message}\n\nRemove it anyway?`)) return;
      await api(`/api/sources/${id}?cascade=true`, { method: 'DELETE' });
      toast('Removed, along with its worksheets');
    }
    await loadLibrary(); await loadBatches();
  }));

  // The forward step only makes sense once there's something to build from.
  $('#toCreate').hidden = state.sources.length === 0;

  fillSourceSelect();
}

function fillSourceSelect() {
  const sel = $('#sourceSelect');
  if (!sel) return;
  const keep = sel.value;
  sel.innerHTML = state.sources.length
    ? state.sources.map(s => `<option value="${s.id}">${esc(s.filename)}${
        s.likely_has_questions === false ? '  (⚠ activity sheet)' : ''}</option>`).join('')
    : '<option value="">Add a worksheet in the Library first</option>';
  if (keep) sel.value = keep;
  showSourceWarning();
}

function showSourceWarning() {
  const sel = $('#sourceSelect');
  const src = state.sources.find(s => s.id === sel?.value);
  const warn = $('#sourceWarning');
  if (warn) warn.hidden = !src || src.likely_has_questions !== false;
}

$('#driveForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = e.target.querySelector('button');
  btn.disabled = true; btn.textContent = 'Fetching…';
  try {
    await api('/api/sources/from-drive', form({ link: e.target.link.value }));
    toast('Added from Drive'); e.target.reset(); await loadLibrary();
  } catch (err) { toast(err.message, 5000); }
  btn.disabled = false; btn.textContent = 'Add from Drive';
});

$('#uploadForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = e.target.querySelector('button');
  const fd = new FormData();
  fd.append('file', e.target.file.files[0]);
  btn.disabled = true; btn.textContent = 'Uploading…';
  try {
    await api('/api/sources/upload', { method: 'POST', body: fd });
    toast('Uploaded'); e.target.reset(); await loadLibrary();
  } catch (err) { toast(err.message, 5000); }
  btn.disabled = false; btn.textContent = 'Upload PDF';
});

/* ── create ──────────────────────────────────────────────── */
$('#createForm').addEventListener('submit', async e => {
  e.preventDefault();
  const f = e.target;
  const bulk = $('#allSources').checked;
  if (!bulk && !f.source_id.value) { toast('Add a worksheet to the library first'); return; }
  if (bulk && !state.sources.length) { toast('The library is empty'); return; }

  const dims = $$('#varyOptions .chip.on').map(c => c.dataset.dim);
  const btn = f.querySelector('button[type=submit]');
  const st = $('#createStatus');
  btn.disabled = true;
  st.className = 'status';
  st.innerHTML = `<span class="spinner"></span>Writing ${f.variant_count.value} worksheet(s)…`;
  $('#createToReview').hidden = true;
  $('#jobToReview').hidden = true;

  const settings = {
    grade: f.grade.value,
    difficulty: f.difficulty.value,
    variant_count: f.variant_count.value,
    question_count: f.question_count.value || 0,
    vary_dimensions: dims.join(','),
    closing_message: f.closing_message.value,
    extra_instructions: f.extra_instructions.value,
    mode: $$('#modeOptions input[name=mode]').filter(r => r.checked)
            .map(r => r.value).join(','),
    template_id: $('#templateSelect').value,
  };

  if (bulk) {
    try {
      const j = await api('/api/generate-all', form({
        ...settings, include_flagged: $('#includeFlagged').checked,
      }));
      st.className = 'status';
      const bits = [`Started — ${j.total} worksheet(s) this run`];
      if (j.skipped) bits.push(`${j.skipped} left for the next`);
      if (j.skipped_low_quality) bits.push(`${j.skipped_low_quality} activity sheet(s) skipped`);
      st.textContent = bits.join(', ') + '.';
      watchJob(j.job_id);
    } catch (err) {
      st.className = 'status err'; st.textContent = err.message;
    }
    btn.disabled = false;
    return;
  }

  try {
    const r = await api('/api/generate', form({
      source_id: f.source_id.value,
      ...settings,
    }));
    st.className = 'status ok';
    st.textContent = `${r.worksheets.length} worksheet(s) ready.`;
    state.pendingBatch = r;
    $('#createToReview').hidden = false;
    goTo('review');
    renderBatch(r);
  } catch (err) {
    st.className = 'status err';
    st.textContent = err.message;
  }
  btn.disabled = false;
});

$('#closingSuggest').addEventListener('click', async () => {
  const topic = $('#closingTopic').value.trim();
  if (!topic) { toast('Type a topic first'); return; }
  const btn = $('#closingSuggest');
  btn.disabled = true; btn.textContent = 'Writing…';
  try {
    const r = await api('/api/closing-message',
      form({ topic, grade: $('#gradeSelect').value, goal: $('#closingGoal').value }));
    $('#createForm').closing_message.value = r.closing_message;
  } catch (e) { toast(e.message, 5000); }
  btn.disabled = false; btn.textContent = 'Suggest';
});

/* ── bulk run progress ───────────────────────────────────── */
async function watchJob(jobId) {
  const panel = $('#jobPanel');
  panel.hidden = false;
  $('#jobFailed').innerHTML = '';

  while (true) {
    let j;
    try { j = await api('/api/jobs/' + jobId); }
    catch { panel.hidden = true; return; }

    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    $('#jobLabel').textContent = j.label;
    $('#jobCount').textContent = `${j.done} of ${j.total} · ${j.made} worksheet(s) written`;
    $('#jobFill').style.width = pct + '%';
    $('#jobCurrent').textContent = j.current ? `Working on ${j.current}…` : '';
    $('#jobFailed').innerHTML = (j.failed || [])
      .slice(0, 5).map(f => `<li>${esc(f)}</li>`).join('');

    if (j.status !== 'running') {
      $('#jobCurrent').textContent = j.failed.length
        ? `Finished — ${j.made} written, ${j.failed.length} didn't come through.`
        : `Finished — ${j.made} worksheet(s) written.`;
      // Only offer the next step if there is actually something to review.
      $('#jobToReview').hidden = j.made === 0;
      await loadBatches();
      return;
    }
    // Batches land one at a time, so refresh Review as the run proceeds.
    await loadBatches();
    await new Promise(r => setTimeout(r, 2500));
  }
}

/* ── review ──────────────────────────────────────────────── */
async function loadBatches() {
  const { batches } = await api('/api/batches');

  // One source can be run several times with different settings. Group by
  // the source worksheet so a bulk run reads as "this worksheet and its
  // versions" rather than a flat list of indistinguishable rows.
  const groups = {};
  batches.forEach(b => (groups[b.source_filename] ||= []).push(b));

  $('#batchList').innerHTML = Object.keys(groups).length
    ? Object.entries(groups).map(([name, runs]) => {
        const made = runs.reduce((n, b) => n + b.made, 0);
        const approved = runs.reduce((n, b) => n + b.approved, 0);
        return `
        <div class="group">
          <div class="grouphead">
            <div class="main">
              <div class="nm">${esc(name)}</div>
              <div class="sub">${made} version(s) across ${runs.length} run(s)</div>
            </div>
            ${approved ? `<span class="pill ok">${approved} approved</span>` : ''}
          </div>
          ${runs.map(b => `
            <div class="row sub-row">
              <div class="main">
                <div class="sub">${esc(state.gradeLabels[b.grade] || 'Grade ' + b.grade)}
                  · ${esc(b.difficulty)} · ${b.made} version(s)</div>
              </div>
              ${b.status === 'failed' ? '<span class="pill warn">Didn\'t complete</span>' : ''}
              <button class="btn sm" data-batch="${b.id}">Open</button>
            </div>`).join('')}
        </div>`; }).join('')
    : '<p class="muted">Nothing created yet.</p>';

  $$('#batchList [data-batch]').forEach(b => b.addEventListener('click', async () => {
    renderBatch(await api('/api/batches/' + b.dataset.batch));
  }));
}

function renderBatch(data) {
  state.currentBatch = data;
  const { batch, worksheets } = data;
  if (!worksheets.length) {
    $('#batchDetail').innerHTML =
      `<p class="status err">${esc(batch.error || "These worksheets didn't come through.")}</p>`;
    return;
  }

  $('#batchDetail').innerHTML = `
    <h2 class="sectiontitle">Grade ${batch.grade} · ${esc(batch.difficulty)} · ${worksheets.length} version(s)</h2>
    <div class="wsgrid">${worksheets.map(renderWorksheet).join('')}</div>`;

  $$('#batchDetail [data-act]').forEach(b =>
    b.addEventListener('click', () => onWorksheetAction(b.dataset.act, b.dataset.id, b)));
}

function renderWorksheet(w) {
  const qs = w.questions.map(q => `
    <div class="qitem">
      <div class="n">${q.number}</div>
      <div class="qt">
        <div class="sec">${esc(q.section)}</div>
        ${esc(q.text)}
        ${q.diagram_id ? `<img src="/diagrams/${esc(q.diagram_id)}.png" alt="">` : ''}
      </div>
    </div>`).join('');

  const v = w.validation || {};
  const vclass = { passed: 'ok', images_failed: 'warn', failed: 'bad',
                    unverified: 'warn' }[v.verdict] || '';
  const issues = (v.problems || []).slice(0, 4);

  return `
    <div class="ws ${esc(w.review_status)}">
      <h3>${esc(w.title)}</h3>
      <div class="skill">${esc(w.skill || '')}</div>
      ${v.verdict ? `<div class="verdict ${vclass}">
          <span class="vlabel">${esc(state.verdicts[v.verdict] || v.verdict)}</span>
          ${issues.length ? `<ul class="vissues">${
            issues.map(p => `<li>${esc(p)}</li>`).join('')}${
            (v.problems || []).length > issues.length
              ? `<li>…and ${v.problems.length - issues.length} more</li>` : ''}</ul>` : ''}
          ${v.image_repair && v.image_repair.fixed.length
            ? `<div class="vnote">${v.image_repair.fixed.length} picture(s) redrawn</div>` : ''}
        </div>` : ''}
      <div class="qlist">${qs}</div>
      <div class="wsfoot">
        <button class="btn sm approve ${w.review_status === 'approved' ? 'on' : ''}"
                data-act="approve" data-id="${w.id}">
          ${w.review_status === 'approved' ? '✓ Approved' : 'Approve'}</button>
        <button class="btn sm reject ${w.review_status === 'rejected' ? 'on' : ''}"
                data-act="reject" data-id="${w.id}">
          ${w.review_status === 'rejected' ? '✕ Rejected' : 'Reject'}</button>
        <button class="btn sm" data-act="edit" data-id="${w.id}">Edit</button>
        <button class="btn sm" data-act="revise" data-id="${w.id}">Ask for a change</button>
        <button class="btn sm" data-act="export" data-id="${w.id}">Preview</button>
      </div>
    </div>`;
}

async function onWorksheetAction(act, id, btn) {
  if (act === 'approve' || act === 'reject') {
    const status = act === 'approve' ? 'approved' : 'rejected';
    await api(`/api/worksheets/${id}/review`, form({ status }));
    toast(act === 'approve' ? 'Approved' : 'Rejected');
    refreshCounts();
    renderBatch(await api('/api/batches/' + state.currentBatch.batch.id));
    return;
  }
  if (act === 'edit') {
    openEditor(id);
    return;
  }
  if (act === 'revise') {
    state.reviseTarget = id;
    $('#reviseText').value = '';
    $('#reviseStatus').textContent = '';
    $('#reviseModal').hidden = false;
    $('#reviseText').focus();
    return;
  }
  if (act === 'export') {
    btn.disabled = true; btn.textContent = 'Preparing…';
    try {
      const r = await api(`/api/worksheets/${id}/export`, { method: 'POST' });
      window.open(r.view_url, '_blank');
    } catch (e) { toast(e.message); }
    btn.disabled = false; btn.textContent = 'Preview';
  }
}

/* ── hand editing ────────────────────────────────────────── */
function openEditor(worksheetId) {
  const ws = (state.currentBatch?.worksheets || []).find(w => w.id === worksheetId);
  if (!ws) { toast('Open the worksheet again first'); return; }

  state.editTarget = worksheetId;
  $('#editStatus').textContent = '';
  $('#editList').innerHTML = ws.questions.map(q => `
    <div class="editq" data-n="${q.number}">
      <div class="editnum">${q.number}<span class="editsec">${esc(q.section)}</span></div>
      <div class="editfields">
        <textarea data-field="text" rows="2">${esc(q.text)}</textarea>
        <input type="text" data-field="answer" value="${esc(q.answer || '')}"
               placeholder="answer">
      </div>
    </div>`).join('');
  $('#editModal').hidden = false;
}

$('#editCancel').addEventListener('click', () => { $('#editModal').hidden = true; });

$('#editSave').addEventListener('click', async () => {
  const questions = {};
  $$('#editList .editq').forEach(row => {
    questions[row.dataset.n] = {
      text: row.querySelector('[data-field=text]').value,
      answer: row.querySelector('[data-field=answer]').value,
    };
  });

  const st = $('#editStatus');
  st.className = 'status';
  st.innerHTML = '<span class="spinner"></span>Saving…';
  $('#editSave').disabled = true;
  try {
    await api(`/api/worksheets/${state.editTarget}/questions`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ questions }),
    });
    $('#editModal').hidden = true;
    toast('Changes saved');
    renderBatch(await api('/api/batches/' + state.currentBatch.batch.id));
  } catch (e) {
    st.className = 'status err';
    st.textContent = e.message;
  }
  $('#editSave').disabled = false;
});

/* ── change requests ─────────────────────────────────────── */
$('#reviseCancel').addEventListener('click', () => { $('#reviseModal').hidden = true; });

$('#reviseGo').addEventListener('click', async () => {
  const instruction = $('#reviseText').value.trim();
  if (!instruction) { $('#reviseStatus').textContent = 'Describe the change first.'; return; }
  const scope = $$('input[name=scope]').find(r => r.checked).value;
  const st = $('#reviseStatus');
  st.className = 'status';
  st.innerHTML = '<span class="spinner"></span>Applying…';
  $('#reviseGo').disabled = true;
  try {
    await api(`/api/worksheets/${state.reviseTarget}/revise`, form({ instruction, scope }));
    $('#reviseModal').hidden = true;
    toast('Change applied');
    renderBatch(await api('/api/batches/' + state.currentBatch.batch.id));
  } catch (e) {
    st.className = 'status err';
    st.textContent = e.message;
  }
  $('#reviseGo').disabled = false;
});

boot().catch(e => toast(e.message, 6000));
