/* Tallowa Components - shared frontend helpers (vanilla JS, no dependencies). */

/* ---------------- auth ---------------- */
function tok(){ return localStorage.getItem('tc_token') || ''; }
function me(){ try{ return JSON.parse(localStorage.getItem('tc_user')||'null'); }catch(e){ return null; } }
if (!tok() && location.pathname !== '/login') location.href = '/login';

async function api(path, opts){
  opts = opts || {};
  opts.headers = Object.assign({'Authorization':'Bearer '+tok()}, opts.headers||{});
  if (opts.body && typeof opts.body !== 'string'){
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  const r = await fetch(path, opts);
  if (r.status === 401){ localStorage.removeItem('tc_token'); location.href='/login'; throw new Error('auth'); }
  if (!r.ok){ const d = await r.json().catch(()=>({})); throw new Error(d.detail || ('Request failed ('+r.status+')')); }
  return r.json();
}

/* ---------------- guided demo mode ----------------
   Reached only via the "Use cases" quick-launch menu (?demo=1). Forces every
   golden-backed AI call on the page straight to its verified cached answer -
   correct and instant, no dependency on a live LLM/KB round-trip - so an SE
   walking a customer through the scripted narrative never hits a slow or
   flaky live call. Direct/manual navigation still calls live as normal. */
const DEMO_MODE = new URLSearchParams(location.search).get('demo') === '1';

/* ---------------- human input simulator ----------------
   A guided demo page (?demo=1) fills its own request fields as if
   someone were actually typing/selecting them - the SE watches the
   same "someone is asking this" moment a live customer call would
   show, then clicks the real action button themselves. Never submits
   anything on its own; only ever touches the field(s) it's given. */
let _simStyleInjected = false;
function _simInjectStyle(){
  if (_simStyleInjected) return;
  _simStyleInjected = true;
  const css = document.createElement('style');
  css.textContent =
    '.sim-typing{outline:2px solid var(--orange);outline-offset:1px;'+
      'background:#FFF7EF!important;transition:outline-color .15s}';
  document.head.appendChild(css);
}
function simulateType(el, text, opts){
  if (typeof el === 'string') el = document.getElementById(el);
  opts = opts || {};
  _simInjectStyle();
  return new Promise(resolve=>{
    el.value = '';
    el.classList.add('sim-typing');
    el.focus();
    let i = 0;
    function step(){
      if (i >= text.length){
        el.classList.remove('sim-typing');
        el.blur();
        resolve();
        return;
      }
      el.value += text[i];
      el.dispatchEvent(new Event('input', {bubbles:true}));
      i++;
      const base = opts.speed || 46;
      const jitter = base * (0.55 + Math.random() * 0.9);
      // a human pauses slightly longer after a space, like thinking mid-word
      const thinking = (text[i-1] === ' ' && Math.random() < 0.3) ? 130 + Math.random()*170 : 0;
      setTimeout(step, jitter + thinking);
    }
    setTimeout(step, opts.delay != null ? opts.delay : 200);
  });
}
function simulateSelect(el, value, opts){
  if (typeof el === 'string') el = document.getElementById(el);
  opts = opts || {};
  _simInjectStyle();
  return new Promise(resolve=>{
    el.classList.add('sim-typing');
    el.focus();
    setTimeout(()=>{
      el.value = value;
      el.dispatchEvent(new Event('change', {bubbles:true}));
      setTimeout(()=>{ el.classList.remove('sim-typing'); el.blur(); resolve(); }, 200);
    }, opts.delay != null ? opts.delay : 320);
  });
}

/* ---------------- format ---------------- */
function money(v){ return '$' + (v==null?0:v).toLocaleString('en-AU',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function n0(v){ return (v==null?0:v).toLocaleString('en-AU',{maximumFractionDigits:0}); }
function dt(s){ return s ? String(s).slice(0,10) : '-'; }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

const BADGE = {
  planned:'grey', released:'blue', in_progress:'orange', quality_hold:'red',
  completed:'green', cancelled:'grey', shipped:'green', draft:'grey',
  submitted:'blue', approved:'blue', in_production:'orange', fulfilled:'green',
  rejected:'red', lost:'red', sent:'blue', confirmed:'blue', partial:'amber',
  received:'green', paid:'green', overdue:'red', staged:'amber',
  despatched:'blue', delivered:'green', available:'green', quarantine:'red',
  hold:'red', consumed:'grey', recalled:'red', in_stock:'green', allocated:'blue',
  open:'red', closed:'green', running:'green', stopped:'red', down:'red',
  maintenance:'amber', active:'green', leave:'amber', in_service:'green',
  minor:'grey', major:'amber', critical:'red', expired:'red', expiring:'amber',
  current:'green', ok:'green', due_soon:'amber', 'released_h':'green'
};
function badge(s){ if(s==null) return '-';
  const k = String(s).toLowerCase();
  return '<span class="b b-'+(BADGE[k]||'grey')+'">'+esc(String(s).replace(/_/g,' '))+'</span>'; }

/* ---------------- tables ---------------- */
/* cols: [{k,label,fmt,cls}] ; opts: {link: row=>url, empty} */
function table(el, cols, rows, opts){
  opts = opts || {};
  if (typeof el === 'string') el = document.getElementById(el);
  if (!rows || !rows.length){ el.innerHTML = '<div class="empty">'+(opts.empty||'Nothing to show yet.')+'</div>'; return; }
  let h = '<table><thead><tr>' + cols.map(c=>'<th'+(c.cls?' class="'+c.cls+'"':'')+'>'+c.label+'</th>').join('') + '</tr></thead><tbody>';
  for (const r of rows){
    h += '<tr'+(opts.link?' class="click" onclick="location.href=\''+opts.link(r)+'\'"':'')+'>';
    for (const c of cols){
      const v = c.fmt ? c.fmt(r[c.k], r) : esc(r[c.k]);
      h += '<td'+(c.cls?' class="'+c.cls+'"':'')+'>'+(v==null||v==='' ? '-' : v)+'</td>';
    }
    h += '</tr>';
  }
  el.innerHTML = h + '</tbody></table>';
}

function kpi(el, items){
  if (typeof el === 'string') el = document.getElementById(el);
  el.innerHTML = items.map(i=>'<div class="kpi '+(i.tone||'')+'"><div class="l">'+i.l+
    '</div><div class="v">'+i.v+'</div></div>').join('');
}

/* ---------------- markdown-lite ---------------- */
function md(t){
  t = esc(t||'');
  t = t.replace(/^######? (.*)$/gm,'<h4>$1</h4>')
       .replace(/^#### (.*)$/gm,'<h4>$1</h4>')
       .replace(/^### (.*)$/gm,'<h3>$1</h3>')
       .replace(/^## (.*)$/gm,'<h2>$1</h2>')
       .replace(/^# (.*)$/gm,'<h1>$1</h1>')
       .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
       .replace(/`([^`]+)`/g,'<code>$1</code>');
  const lines = t.split('\n'); let out=[], inUl=false, inOl=false, lastLi=-1;
  for (const ln of lines){
    // A bullet under an OPEN NUMBERED list reads as a detail line under the
    // item just above it, not a new list, REGARDLESS of indentation - a
    // non-indented bullet between numbered items (e.g. "1. Phase:" /
    // "- detail" / "- detail" / "2. Phase:", the natural AI shape for a
    // numbered plan with a bullet breakdown per step) used to open a <ul>
    // INSIDE the still-open <ol> - invalid nesting that silently swallowed
    // every following numbered item as a flat bullet, losing its number
    // entirely (found live in two sibling apps' demos as a plain restart-at-
    // -1, but this app's own closing/reopening logic made it worse - see
    // md-list-restart fix, 22 Jul). An indented bullet under an open
    // BULLET list folds in the same way (the original, narrower fix).
    const bulletM = ln.match(/^\s*([-*]) (.*)$/);
    const indented = /^\s+[-*] /.test(ln);
    if (bulletM && lastLi>=0 && (inOl || (indented && inUl))){
      out[lastLi] = out[lastLi].replace(/<\/li>$/, '<br>&bull; '+bulletM[2]+'</li>');
      continue;
    }
    if (/^[-*] /.test(ln)){ if(!inUl){out.push('<ul>');inUl=true;} out.push('<li>'+ln.replace(/^[-*] /,'')+'</li>'); lastLi=out.length-1; continue; }
    if (/^\d+[.)] /.test(ln)){ if(!inOl){out.push('<ol>');inOl=true;} out.push('<li>'+ln.replace(/^\d+[.)] /,'')+'</li>'); lastLi=out.length-1; continue; }
    // A blank line BETWEEN list items (a "loose" list - very common in AI
    // answers, one blank line per numbered item) must not close the list,
    // or every item ends up in its own <ol> restarting the count at 1.
    // Only a genuine non-list, non-blank line ends the list.
    if (ln.trim()===''){ if(inUl||inOl) continue; out.push(''); continue; }
    if (inUl){out.push('</ul>');inUl=false;} if (inOl){out.push('</ol>');inOl=false;}
    lastLi=-1;
    if (/^<h\d/.test(ln)) out.push(ln); else out.push('<p>'+ln+'</p>');
  }
  if (inUl) out.push('</ul>'); if (inOl) out.push('</ol>');
  return out.join('\n');
}

/* ---------------- editable AI draft (preview <-> edit toggle) ----------------
   An AI-drafted document (e.g. an 8D report) that a human edits before
   approving. Shows the formatted (md-rendered) version by default - never
   raw markdown source - with an "Edit" affordance that reveals the plain
   textarea; "Done editing" re-renders the preview from the edited text.
   Returns {getText, setText} so the caller's approve action always reads
   the current source regardless of whether the user ever opened the editor. */
function draftPreview(el, initialText){
  if (typeof el === 'string') el = document.getElementById(el);
  let text = initialText, editing = false;
  const id = 'dp' + Math.random().toString(36).slice(2, 8);
  function render(){
    if (editing){
      el.innerHTML =
        '<textarea id="'+id+'ta" style="min-height:220px">'+esc(text)+'</textarea>'+
        '<div class="row" style="margin-top:6px"><button class="btn ghost" id="'+id+'done">Done editing</button></div>';
      document.getElementById(id+'done').onclick = ()=>{
        text = document.getElementById(id+'ta').value;
        editing = false; render();
      };
    } else {
      el.innerHTML =
        '<div class="ai-answer">'+md(text)+'</div>'+
        '<div class="row" style="margin-top:6px"><button class="btn ghost" id="'+id+'edit">Edit</button></div>';
      document.getElementById(id+'edit').onclick = ()=>{ editing = true; render(); };
    }
  }
  render();
  return {
    getText: ()=>text,
    setText: t=>{ text = t; editing = false; render(); },
  };
}

/* ---------------- rich structured-answer panel ----------------
   The agent's prose answer is a summary OVER real rows the tool call
   already returned - render the rows themselves as a product-grade panel
   (headline metric strip + a formatted, severity-badged table) rather than
   flattening them back into a numbered list. Generic: infers column roles
   from field-name conventions shared across every ERP list endpoint,
   reusing badge()/money()/dt() so it matches every other table in the app.
   rowGroups: [{tool, label, rows:[{...}]}] - one per tool call this turn. */
function _isMoneyKey(k){ return /^(total|amount|price|cost|value|subtotal|outstanding|balance)/i.test(k); }
function _isDateKey(k){ return /(_on|_at|_date)$/i.test(k); }
function _isIdKey(k){ return /_no$/i.test(k) || k === 'code'; }
function _isNameKey(k){ return /_name$/i.test(k) || k === 'name' || k === 'scope_label' || k === 'title'; }
function _isReasonKey(k){ return /(reason|note|message)$/i.test(k); }
function _looksLikeDate(v){ return typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v); }

function _inferRowSchema(rows){
  const keys = Object.keys(rows[0] || {});
  const pick = (test, dataTest) => keys.find(k => test(k) && (!dataTest || rows.some(r=>dataTest(r[k]))));
  const idKey = pick(_isIdKey) || (keys.includes('id') ? 'id' : null);
  const nameKey = pick(_isNameKey);
  const statusKey = keys.includes('status') ? 'status' : null;
  // "total"/"amount"/"outstanding"/"balance" beat "subtotal"/"price"/"cost" -
  // a row's own grand-total field should win over a partial/component figure
  // (invoices carry both subtotal AND total; a plain name-pattern-order find
  // picked whichever came first in the object, which was the wrong one).
  const moneyPriority = ['total','amount','outstanding','balance','subtotal','price','cost','value'];
  let moneyKey = null;
  for (const want of moneyPriority){
    const hit = keys.find(k => k.toLowerCase()===want && rows.some(r=>typeof r[k]==='number'));
    if (hit){ moneyKey = hit; break; }
  }
  if (!moneyKey) moneyKey = pick(_isMoneyKey, v=>typeof v==='number');
  // prefer a "due"-flavoured date - it's what most hero questions care about
  const dateKey = keys.find(k=>/due/i.test(k) && _isDateKey(k) && rows.some(r=>_looksLikeDate(r[k])))
    || pick(_isDateKey, _looksLikeDate);
  const reasonKey = pick(_isReasonKey);
  return { idKey, nameKey, statusKey, moneyKey, dateKey, reasonKey };
}

function _isUrgent(status){
  if (!status) return false;
  const c = BADGE[String(status).toLowerCase()];
  return c === 'red' || c === 'amber';
}

function _daysAgo(dateStr){
  const d = new Date(dateStr);
  if (isNaN(d)) return null;
  return Math.round((Date.now() - d.getTime()) / 86400000);
}

/* Returns '' if none of the row groups are table-shaped (e.g. a deeply
   nested trace payload) - the caller should fall back to prose-only. */
function richAnswerHtml(rowGroups){
  const usable = (rowGroups||[]).filter(g => g.rows && g.rows.length && (()=>{
    const s = _inferRowSchema(g.rows);
    return s.nameKey || s.moneyKey || s.statusKey || s.dateKey || s.idKey;
  })());
  if (!usable.length) return '';

  return usable.map(g => {
    const rows = g.rows, s = _inferRowSchema(rows);
    const urgentRows = s.statusKey ? rows.filter(r=>_isUrgent(r[s.statusKey])) : [];
    const metricRows = urgentRows.length ? urgentRows : rows;

    const metrics = [];
    const metricLabel = (urgentRows.length && s.statusKey)
      ? esc(String(metricRows[0][s.statusKey]).replace(/_/g,' '))
      : 'record(s)';
    metrics.push({l: urgentRows.length ? 'Flagged' : 'Total', v: n0(metricRows.length)+' '+metricLabel});
    if (s.moneyKey){
      const sum = metricRows.reduce((a,r)=>a+(Number(r[s.moneyKey])||0),0);
      metrics.push({l:'Outstanding', v: money(sum)});
    }
    if (s.dateKey){
      const ages = metricRows.map(r=>_daysAgo(r[s.dateKey])).filter(d=>d!=null && d>0);
      if (ages.length) metrics.push({l:'Oldest', v: Math.max(...ages)+' day(s)'});
    }

    const sorted = rows.slice().sort((a,b)=>{
      if (s.statusKey){
        const au=_isUrgent(a[s.statusKey])?0:1, bu=_isUrgent(b[s.statusKey])?0:1;
        if (au!==bu) return au-bu;
      }
      if (s.moneyKey) return (Number(b[s.moneyKey])||0)-(Number(a[s.moneyKey])||0);
      return 0;
    });
    const maxMoney = s.moneyKey ? Math.max(1, ...rows.map(r=>Number(r[s.moneyKey])||0)) : 0;

    let head = '<tr>';
    if (s.idKey) head += '<th>'+esc(s.idKey.replace(/_/g,' '))+'</th>';
    if (s.nameKey) head += '<th>'+esc(s.nameKey.replace(/_/g,' '))+'</th>';
    if (s.statusKey) head += '<th>status</th>';
    if (s.dateKey) head += '<th>'+esc(s.dateKey.replace(/_on$|_at$/,'').replace(/_/g,' '))+'</th>';
    if (s.moneyKey) head += '<th class="num">'+esc(s.moneyKey.replace(/_/g,' '))+'</th>';
    if (s.reasonKey) head += '<th>detail</th>';
    head += '</tr>';

    const body = sorted.map(r=>{
      const urgent = s.statusKey && _isUrgent(r[s.statusKey]);
      let row = '<tr'+(urgent?' class="urgent-row"':'')+'>';
      if (s.idKey) row += '<td><span class="mono">'+esc(r[s.idKey])+'</span></td>';
      if (s.nameKey) row += '<td>'+esc(r[s.nameKey])+'</td>';
      if (s.statusKey) row += '<td>'+badge(r[s.statusKey])+'</td>';
      if (s.dateKey) row += '<td>'+dt(r[s.dateKey])+'</td>';
      if (s.moneyKey){
        const v = Number(r[s.moneyKey])||0;
        const pct = Math.round(v/maxMoney*100);
        row += '<td class="num"><span class="amtbar"><span style="width:'+pct+'%"></span></span>'+money(v)+'</td>';
      }
      if (s.reasonKey){
        const full=String(r[s.reasonKey]||'');
        row += '<td class="hint">'+esc(full.length>110?full.slice(0,108)+'…':full)+'</td>';
      }
      row += '</tr>';
      return row;
    }).join('');

    return '<div class="rich-group">'+
      '<div class="kpis">'+metrics.map(m=>'<div class="kpi"><div class="l">'+esc(m.l)+'</div><div class="v">'+m.v+'</div></div>').join('')+'</div>'+
      '<table><thead>'+head+'</thead><tbody>'+body+'</tbody></table>'+
      '</div>';
  }).join('');
}

/* ---------------- citations ----------------
   One citation entry per cited PASSAGE, not per source document - a document
   quoted from several paragraphs (common once a KB doc is well-matched)
   otherwise shows as the same filename pill repeated up to 8 times, which
   reads as a rendering glitch rather than strong evidence. Group by the
   document's real identity (rid - the retrieval system's resource id - falls
   back to file/title only for shapes that don't carry one, e.g. kb_snippets'
   hits) and show each source once, with a x-count when it was cited more
   than once - the repeat-citation signal is worth keeping, just not as
   duplicate pills. All of that source's snippets stay in the tooltip so
   hovering still surfaces every passage, not just the first. */
function citesHtml(citations){
  if (!citations || !citations.length) return '';
  const order = [], groups = new Map();
  citations.forEach((c,i)=>{
    const key = c.rid || c.file || c.title || ('cite'+i);
    let g = groups.get(key);
    if (!g){ g = {label: c.title || c.file || ('source '+(i+1)), snippets: []}; groups.set(key, g); order.push(g); }
    if (c.snippet) g.snippets.push(c.snippet);
  });
  return '<div class="cites">' + order.map(g=>
    '<span class="cite" title="'+esc(g.snippets.join('\n\n'))+'">'+esc(g.label)+
    (g.snippets.length>1 ? ' <span style="color:var(--muted);font-weight:600">&times;'+g.snippets.length+'</span>' : '')+
    '</span>').join('') + '</div>';
}

/* ---------------- workflow stepper ----------------
   A horizontal spine naming the real steps of a multi-stage workflow, so a
   reviewer can always see what process is running, where they are in it,
   what just happened, and what comes next. Purely presentational - callers
   still own every API call and business decision; this only reflects state
   back. Injects its own <style> once on first use (shared across pages, per
   the house rule to keep this out of shell.html).
   workflowStepper(el, steps) - steps: [{key,label}]. Returns {set,get}.
   set(key, status, {detail, trace, authority}):
     status - 'pending' (not reached) / 'current' (do this next) /
       'done' (completed) / 'blocked' (blocked on a human's approval) /
       'skipped' (not on this path, e.g. no shortage so no expedite needed).
     detail  - one-line factual result ("7 invoices matched the same cause"),
               not a re-narration.
     trace   - compact "what the agent queried, how long it took" line; omit
               for pure human-decision steps (no agent trace to show).
     authority - short pill naming the authority a decision step exercises
               (e.g. "Quality inspector") - shown regardless of status so the
               gate is legible before as well as after it fires. */
let _wfStyleInjected = false;
function _wfInjectStyle(){
  if (_wfStyleInjected) return;
  _wfStyleInjected = true;
  const css = document.createElement('style');
  css.textContent =
    '.wf{display:flex;align-items:flex-start;margin-bottom:18px}'+
    '.wf-step{flex:1;min-width:0;padding-right:8px}'+
    '.wf-step:last-child{flex:0 1 auto;min-width:120px;padding-right:0}'+
    '.wf-top{display:flex;align-items:center}'+
    '.wf-dot{width:24px;height:24px;border-radius:50%;flex-shrink:0;display:flex;'+
      'align-items:center;justify-content:center;font-size:11px;font-weight:700;'+
      'border:1.5px solid var(--line);background:#fff;color:var(--muted);transition:all .15s}'+
    '.wf-line{flex:1;height:1.5px;background:var(--line);margin:0 3px}'+
    '.wf-step:last-child .wf-line{display:none}'+
    '.wf-label{font-size:12px;font-weight:650;margin-top:8px;color:var(--ink)}'+
    '.wf-auth{font-size:8.5px;letter-spacing:.08em;text-transform:uppercase;background:var(--chip);'+
      'color:var(--muted);border-radius:3px;padding:1.5px 5px;margin-left:6px;vertical-align:1px;white-space:nowrap}'+
    '.wf-trace{font-size:10.5px;color:#8892A0;margin-top:4px;font-family:ui-monospace,Menlo,monospace;line-height:1.4}'+
    '.wf-detail{font-size:11.5px;color:var(--muted);margin-top:3px;line-height:1.45}'+
    '.wf-step.done .wf-dot{background:var(--ok);border-color:var(--ok);color:#fff}'+
    '.wf-step.done .wf-line{background:var(--ok)}'+
    '.wf-step.done .wf-detail{color:var(--ink)}'+
    '.wf-step.current .wf-dot{background:var(--orange);border-color:var(--orange);color:#fff;'+
      'box-shadow:0 0 0 3px rgba(232,117,42,.18)}'+
    '.wf-step.current .wf-label{color:var(--orange)}'+
    '.wf-step.blocked .wf-dot{background:#fff;border-color:var(--warn);color:var(--warn)}'+
    '.wf-step.blocked .wf-label{color:var(--warn)}'+
    '.wf-step.blocked .wf-auth{background:#F8ECD9;color:var(--warn)}'+
    '.wf-step.blocked .wf-detail{color:var(--warn)}'+
    '.wf-step.pending .wf-label{color:var(--muted);font-weight:600}'+
    '.wf-step.pending .wf-detail{font-style:italic}'+
    '.wf-step.skipped .wf-dot{color:#B7BDC4;border-style:dashed}'+
    '.wf-step.skipped .wf-label{color:#9AA3AB}'+
    '.wf-step.skipped .wf-detail{color:#9AA3AB;font-style:italic}';
  document.head.appendChild(css);
}
function workflowStepper(el, steps){
  if (typeof el === 'string') el = document.getElementById(el);
  _wfInjectStyle();
  const st = {};
  steps.forEach((s,i)=>{ st[s.key] = {status: i===0?'current':'pending', detail:'', trace:'', authority:''}; });
  function render(){
    el.innerHTML = '<div class="wf">' + steps.map((s,i)=>{
      const x = st[s.key];
      const icon = x.status==='done' ? '&#10003;' : (x.status==='blocked' ? '!' : (x.status==='skipped' ? '&ndash;' : String(i+1)));
      return '<div class="wf-step '+x.status+'">'
        +'<div class="wf-top"><div class="wf-dot">'+icon+'</div><div class="wf-line"></div></div>'
        +'<div class="wf-label">'+esc(s.label)+(x.authority?'<span class="wf-auth">'+esc(x.authority)+'</span>':'')+'</div>'
        +(x.trace?'<div class="wf-trace">'+x.trace+'</div>':'')
        +(x.detail?'<div class="wf-detail">'+esc(x.detail)+'</div>':'')
        +'</div>';
    }).join('') + '</div>';
  }
  render();
  return {
    set(key, status, opts){
      const s = st[key]; if (!s) return;
      opts = opts || {};
      s.status = status;
      if ('detail' in opts) s.detail = opts.detail;
      if ('trace' in opts) s.trace = opts.trace;
      if ('authority' in opts) s.authority = opts.authority;
      render();
    },
    get(key){ return st[key]; },
  };
}
/* Compact "what the agent queried, how long it took" line for a done step. */
function wfTrace(queried, ms){
  return 'Queried ' + queried + (ms!=null ? ' &middot; ' + ms + 'ms' : '');
}

/* ---------------- AI panel ----------------
   aiPanel(el, {endpoint, title, tag, body, golden, autorun, questionInput,
                placeholder, chips:[...], renderExtra, onResult(d, ms)}) */
function aiPanel(el, cfg){
  if (typeof el === 'string') el = document.getElementById(el);
  const id = 'aip' + Math.random().toString(36).slice(2,8);
  el.innerHTML =
    '<div class="ai-panel">'+
    '<h3>'+esc(cfg.title)+' <span class="ai-tag">'+(cfg.tag||'GROUNDED AI')+'</span><span class="sp"></span>'+
    '<button class="btn orange" id="'+id+'go">'+(cfg.button||'Generate')+'</button></h3>'+
    (cfg.questionInput ? '<div class="row"><input type="text" class="grow" id="'+id+'q" placeholder="'+esc(cfg.placeholder||'Ask a question...')+'"></div>' : '')+
    (cfg.chips ? '<div class="chiprow">'+cfg.chips.map(c=>'<span class="qchip">'+esc(c)+'</span>').join('')+'</div>' : '')+
    '<div id="'+id+'out"></div></div>';
  const out = document.getElementById(id+'out');
  const qEl = document.getElementById(id+'q');
  if (cfg.chips && qEl) el.querySelectorAll('.qchip').forEach(ch=>ch.onclick=()=>{ qEl.value=ch.textContent; run(); });
  async function run(){
    const body = Object.assign({}, typeof cfg.body==='function'?cfg.body():cfg.body||{});
    if (qEl && qEl.value.trim()) body.query = qEl.value.trim();
    if (cfg.golden){ body.golden = cfg.golden; if (DEMO_MODE) body.mode = 'cached'; }
    out.innerHTML = '<div class="shimmer"><span class="spin"></span>Working - querying live data and generating...</div>';
    const t0 = performance.now();
    try{
      const d = await api(cfg.endpoint, {method:'POST', body});
      const ms = Math.round(performance.now()-t0);
      if (d.empty || (!d.answer && !d.draft && !d.triage)){
        out.innerHTML = '<div class="empty">No grounded answer was available for that - try rephrasing, or check the source data.</div>';
        if (cfg.onResult) cfg.onResult(null, ms);
        return;
      }
      let h = '';
      if (d.answer) h += '<div class="ai-answer">'+md(d.answer)+'</div>';
      if (cfg.renderExtra) h += cfg.renderExtra(d);
      h += citesHtml(d.citations);
      const g = [];
      if (d.data_used) for (const [k,v] of Object.entries(d.data_used)){ if (typeof v!=='object') g.push(k.replace(/_/g,' ')+': '+v); }
      if (g.length) h += '<div class="grounding">Grounded in live plant data - '+g.join(' &middot; ')+(d.cached?' &middot; cached result':'')+'</div>';
      else if (d.citations && d.citations.length) h += '<div class="grounding">Grounded in '+d.citations.length+' plant document extract(s)'+(d.cached?' &middot; cached result':'')+'</div>';
      out.innerHTML = h;
      if (cfg.onResult) cfg.onResult(d, ms);
    }catch(ex){ out.innerHTML = '<div class="empty">Could not generate: '+esc(ex.message)+'</div>'; }
  }
  document.getElementById(id+'go').onclick = run;
  if (qEl) qEl.addEventListener('keydown', e=>{ if(e.key==='Enter') run(); });
  if (cfg.autorun) run();
  return {run};
}

/* ---------------- NDJSON stream ---------------- */
async function streamNdjson(path, body, onEvent){
  const r = await fetch(path, {method:'POST',
    headers:{'Authorization':'Bearer '+tok(),'Content-Type':'application/json'},
    body: JSON.stringify(body)});
  if (r.status === 401){ location.href='/login'; return; }
  const reader = r.body.getReader(); const dec = new TextDecoder();
  let buf='';
  for(;;){
    const {done, value} = await reader.read();
    if (done) break;
    buf += dec.decode(value, {stream:true});
    let i;
    while((i = buf.indexOf('\n')) >= 0){
      const line = buf.slice(0,i).trim(); buf = buf.slice(i+1);
      if (!line) continue;
      try{ onEvent(JSON.parse(line)); }catch(e){}
    }
  }
}

/* ---------------- agent trace panel ----------------
   A single grounded call (live data queried, documents consulted, answer
   composed) shown as a live animated step trace - the same visual
   language as the Ops Assistant's own agent trace, reused here for a
   single templated call rather than a free-form question, so every AI
   call in the app reads as the SAME retrieval agent at work, never a
   generic spinner. runAgentTrace(el, endpoint, body, opts) streams the
   call's NDJSON progress (start/tool_call/tool_result/doc_search/
   composing/fallback/result/error/done - see stream_feature in ai.py),
   renders each step as it lands, then renders the final answer
   (opts.renderAnswer(data), or a default markdown+citations block) once
   the `result` event arrives. Returns a Promise<data|null> so the caller
   can pick up field values (data_used, ctp, fields...) exactly as it
   would from a buffered call. */
let _traceStyleInjected = false;
function _traceInjectStyle(){
  if (_traceStyleInjected) return;
  _traceStyleInjected = true;
  const css = document.createElement('style');
  css.textContent =
    '.trace-wrap{background:var(--card);border:1px solid var(--line);border-radius:8px;'+
      'padding:14px 16px;margin-bottom:16px}'+
    '.trace-head{display:flex;align-items:center;gap:10px;margin-bottom:2px}'+
    '.trace-head h3{font-size:13.5px;margin:0}'+
    '.trace-timer{margin-left:auto;font-size:11.5px;color:var(--muted);'+
      'font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:6px}'+
    '.trace-sub{font-size:11px;color:var(--muted);margin:3px 0 9px;padding-bottom:9px;'+
      'border-bottom:1px solid var(--line)}'+
    '.trace{margin-top:2px;display:flex;flex-direction:column;gap:7px}'+
    '.tstep{display:flex;align-items:flex-start;gap:10px;padding:8px 10px;border-radius:7px;'+
      'background:#FBFAF7;border:1px solid var(--line);font-size:12.6px;'+
      'animation:tracein .28s ease both}'+
    '@keyframes tracein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}'+
    '.tstep.done{background:#fff}'+
    '.tstep.err{background:#FCEEEC;border-color:#F0CCC5}'+
    '.tstep .icon{flex-shrink:0;width:16px;height:16px;margin-top:1px;position:relative}'+
    '.tstep .icon .ring{width:16px;height:16px;border-radius:50%;border:2px solid var(--line);'+
      'border-top-color:var(--orange);animation:tracesp .8s linear infinite}'+
    '@keyframes tracesp{to{transform:rotate(360deg)}}'+
    '.tstep .icon .tick{width:16px;height:16px;border-radius:50%;background:var(--navy);'+
      'color:#fff;font-size:10px;line-height:16px;text-align:center;font-weight:700}'+
    '.tstep.err .icon .tick{background:var(--bad)}'+
    '.tstep .icon .dim{width:6px;height:6px;border-radius:50%;background:var(--muted);margin:5px}'+
    '.tstep .body{flex:1;min-width:0}'+
    '.tstep .lbl{font-weight:600;color:var(--ink)}'+
    '.tstep.err .lbl{color:var(--bad)}'+
    '.tstep .det{color:var(--muted);font-size:11.5px;margin-top:1px;'+
      'font-family:ui-monospace,Menlo,monospace}'+
    '.tstep .dur{flex-shrink:0;font-size:10.5px;color:var(--muted);'+
      'font-variant-numeric:tabular-nums;margin-top:2px}'+
    '.tstep.compose{background:#F3EFE3;border-color:#E7DCC0}'+
    '.tstep.plan{background:#EDF3F8;border-color:#D6E3EE}'+
    '.mcpline{margin-top:4px;font-size:10.8px;color:var(--muted);display:flex;align-items:center;'+
      'gap:6px;font-family:ui-monospace,Menlo,monospace}'+
    '.mcpline b{color:var(--ink);font-weight:600}'+
    '.mcpline .b{font-size:8.5px;padding:1px 5px;letter-spacing:.06em}'+
    '.fallback-note{font-size:11.5px;color:var(--warn);background:#FBF4E6;'+
      'border:1px solid #F0DFB8;border-radius:7px;padding:7px 10px;margin:2px 0}'+
    'details.tracewrap{margin-top:4px}'+
    'details.tracewrap summary{cursor:pointer;font-size:11.5px;color:var(--muted);'+
      'list-style:none;padding:4px 0;user-select:none}'+
    'details.tracewrap summary::-webkit-details-marker{display:none}'+
    "details.tracewrap summary:before{content:'\\25B8 ';color:var(--orange);font-size:10px}"+
    "details.tracewrap[open] summary:before{content:'\\25BE ';}"+
    'details.tracewrap summary:hover{color:var(--ink)}';
  document.head.appendChild(css);
}
function _traceIcon(kind){
  if (kind==='pending') return '<div class="icon"><div class="ring"></div></div>';
  if (kind==='ok') return '<div class="icon"><div class="tick">&check;</div></div>';
  if (kind==='err') return '<div class="icon"><div class="tick">&times;</div></div>';
  return '<div class="icon"><div class="dim"></div></div>';
}
function _traceFmtS(ms){ return (ms/1000).toFixed(1)+'s'; }
function _traceStepCard(cls, iconKind, label, detail, durMs){
  return '<div class="tstep '+cls+'">'+_traceIcon(iconKind)+
    '<div class="body"><div class="lbl">'+esc(label)+'</div>'+
    (detail?'<div class="det">'+esc(detail)+'</div>':'')+'</div>'+
    (durMs!=null?'<div class="dur">'+_traceFmtS(durMs)+'</div>':'')+'</div>';
}
function _traceMcpLine(ev){
  if (!ev || !ev.tool) return '';
  const tag = ev.mcp_kind==='prompt' ? 'MCP PROMPT' : 'MCP';
  const route = ev.mcp_route ? ' <span>'+esc(ev.mcp_route)+'</span>' : '';
  return '<div class="mcpline"><span class="b b-navy">'+tag+'</span><b>'+esc(ev.tool)+'</b>'+route+'</div>';
}

function runAgentTrace(el, endpoint, body, opts){
  if (typeof el === 'string') el = document.getElementById(el);
  opts = opts || {};
  _traceInjectStyle();
  const t0 = Date.now();
  el.innerHTML =
    '<div class="trace-wrap">'+
      '<div class="trace-head"><h3>'+esc(opts.title||'Watching the agent work')+'</h3>'+
        '<div class="trace-timer"><span class="livedot"></span><span class="tlabel">Connecting to the retrieval agent&hellip;</span></div>'+
      '</div>'+
      (opts.sub ? '<div class="trace-sub">'+opts.sub+'</div>' : '')+
      '<div class="trace"></div>'+
    '</div>'+
    '<div class="trace-ans"></div>';
  const wrap = el.querySelector('.trace-wrap');
  const trace = el.querySelector('.trace');
  const ansEl = el.querySelector('.trace-ans');
  const timerLabel = el.querySelector('.tlabel');
  // Keyed by tool name, not one shared slot: a multi-step agent run can
  // have more than one tool_call in flight before its tool_result lands
  // (see the Ops Assistant's own trace for the same reasoning).
  let pendingByTool = {}, composeCard = null, stepCount = 0, finished = false, result = null;

  function setTimer(txt){ timerLabel.textContent = txt; }
  function tick(){ if(!finished) setTimer('Working - '+((Date.now()-t0)/1000).toFixed(0)+'s elapsed'); }
  const ticker = setInterval(tick, 1000);
  function push(html){
    stepCount++;
    trace.insertAdjacentHTML('beforeend', html);
    trace.scrollTop = trace.scrollHeight;
    return trace.lastElementChild;
  }

  return streamNdjson(endpoint, Object.assign({}, body, {stream:true}), ev=>{
    if (ev.type==='heartbeat'){ tick(); return; }
    else if (ev.type==='plan'){
      setTimer('Planning the lookup…');
      push(_traceStepCard('plan', 'plan', ev.label||'Planning the lookup', ev.detail));
    }
    else if (ev.type==='tool_call'){
      setTimer((ev.label||'Working')+'…');
      const card = push('<div class="tstep">'+_traceIcon('pending')+
        '<div class="body"><div class="lbl">'+esc(ev.label)+'</div>'+
        (ev.detail?'<div class="det">'+esc(ev.detail)+'</div>':'')+
        _traceMcpLine(ev)+'</div></div>');
      (pendingByTool[ev.tool]=pendingByTool[ev.tool]||[]).push(card);
    }
    else if (ev.type==='tool_result'){
      const q = pendingByTool[ev.tool];
      const card = (q && q.length) ? q.shift() : null;
      const ok = ev.ok !== false;
      const cls = ok ? 'done' : 'err';
      const html = _traceIcon(ok?'ok':'err')+
        '<div class="body"><div class="lbl">'+esc(ev.label)+'</div>'+
        (ev.detail?'<div class="det">'+esc(ev.detail)+'</div>':'')+
        _traceMcpLine(ev)+'</div>'+
        (ev.duration_ms!=null?'<div class="dur">'+_traceFmtS(ev.duration_ms)+'</div>':'');
      if (card){ card.className = 'tstep '+cls; card.innerHTML = html; }
      else { push('<div class="tstep '+cls+'">'+html+'</div>'); }
    }
    else if (ev.type==='doc_search'){
      setTimer((ev.label||'Reading plant documents')+'…');
      push(_traceStepCard('done', 'ok', ev.label||'Reading plant documents', ev.detail));
    }
    else if (ev.type==='composing'){
      setTimer((ev.label||'Composing the answer')+'…');
      if (composeCard){ composeCard.querySelector('.lbl').textContent = ev.label||''; }
      else{
        composeCard = push('<div class="tstep compose">'+_traceIcon('pending')+
          '<div class="body"><div class="lbl">'+esc(ev.label||'')+'</div></div></div>');
      }
    }
    else if (ev.type==='fallback'){
      ansEl.insertAdjacentHTML('beforeend', '<div class="fallback-note">'+esc(ev.message)+'</div>');
    }
    else if (ev.type==='result'){
      finished = true;
      clearInterval(ticker);
      if (composeCard){ composeCard.className='tstep done';
        composeCard.innerHTML = _traceIcon('ok')+'<div class="body"><div class="lbl">Answer composed</div></div>'; }
      setTimer('Done - '+((Date.now()-t0)/1000).toFixed(1)+'s');
      const data = ev.data || {};
      const answerHtml = opts.renderAnswer ? opts.renderAnswer(data) :
        (data.answer ? '<div class="ai-answer">'+md(data.answer)+'</div>'+citesHtml(data.citations)
          : '<div class="empty">No grounded answer was available for that - try again.</div>');
      ansEl.insertAdjacentHTML('beforeend',
        '<div style="border-top:1.5px solid var(--line);padding-top:12px;margin-top:2px">'+answerHtml+'</div>'+
        '<details class="tracewrap"><summary>How this was answered ('+stepCount+' step(s))</summary></details>');
      const dsum = ansEl.querySelector('details.tracewrap');
      if (wrap && dsum) dsum.appendChild(wrap);
      result = data;
    }
    else if (ev.type==='error'){
      finished = true; clearInterval(ticker); setTimer('');
      ansEl.insertAdjacentHTML('beforeend', '<div class="empty">'+esc(ev.message)+'</div>');
    }
  }).then(()=>{ clearInterval(ticker);
    return result;
  }).catch(ex=>{
    clearInterval(ticker);
    ansEl.innerHTML += '<div class="empty">Stream failed: '+esc(ex.message)+'</div>';
    return null;
  });
}

/* ---------------- modal ---------------- */
function modal(html){
  const bg = document.getElementById('modalbg');
  document.getElementById('modal').innerHTML = html;
  bg.style.display='flex';
  bg.onclick = e=>{ if(e.target===bg) bg.style.display='none'; };
}
function closeModal(){ document.getElementById('modalbg').style.display='none'; }

/* ---------------- shell init ---------------- */
(function(){
  if (location.pathname === '/login') return;
  const u = me();
  const who = document.getElementById('who');
  if (who && u) who.innerHTML = '<b>'+esc(u.name)+'</b><br>'+esc(u.role.replace(/_/g,' '));
  const lo = document.getElementById('logout');
  if (lo) lo.onclick = ()=>{ localStorage.removeItem('tc_token'); localStorage.removeItem('tc_user'); location.href='/login'; };
  // nav highlight: longest matching prefix
  let best=null;
  document.querySelectorAll('#nav a').forEach(a=>{
    const href=a.getAttribute('href');
    if (href!=='/docs' && (location.pathname===href || (href!=='/' && location.pathname.startsWith(href))))
      if(!best || href.length>best.getAttribute('href').length) best=a;
  });
  if (!best) best=document.querySelector('#nav a[href="/"]') && location.pathname==='/' ? document.querySelector('#nav a[href="/"]') : best;
  if (best) best.classList.add('on');
  // notifications
  const bell=document.getElementById('bell'), pop=document.getElementById('notifpop');
  if (bell) api('/api/notifications/').then(rows=>{
    const unread=rows.filter(r=>!r.read);
    const dot=document.getElementById('belldot');
    if (unread.length){ dot.style.display='inline-block'; dot.textContent=unread.length; }
    bell.onclick=()=>{
      if (pop.style.display==='block'){ pop.style.display='none'; return; }
      pop.innerHTML = rows.length ? rows.map(r=>
        '<div class="n" onclick="location.href=\''+r.link+'\'"><b>'+esc(r.title)+'</b><p>'+esc(r.body)+'</p></div>').join('')
        : '<div class="n"><p>No notifications.</p></div>';
      pop.style.display='block';
      api('/api/notifications/read-all',{method:'POST'}).then(()=>{document.getElementById('belldot').style.display='none';});
    };
  }).catch(()=>{});
  // use-case demo guide (SE navigation aid, not customer-facing chrome)
  const ucbtn=document.getElementById('ucbtn'), ucpop=document.getElementById('ucpop');
  if (ucbtn && ucpop) {
    const USE_CASES=[
      {href:'/quality?demo=1',      t:'1. Quality alert → 8D',   d:'FPY breach, root-cause suspects, contain the lot, auto-drafted 8D'},
      {href:'/ap-invoices?demo=1',  t:'2. AP invoice auto-fix',        d:'Explain the error, find the shared cause, batch-fix & post'},
      {href:'/ctp?demo=1',          t:'3. Capable-to-Promise',         d:'Real-time delivery commit, what-if expedite, dual approval'}
    ];
    ucpop.innerHTML = USE_CASES.map(u=>
      '<a class="u" href="'+u.href+'"><b>'+esc(u.t)+'</b><p>'+esc(u.d)+'</p></a>').join('');
    ucbtn.onclick=(e)=>{ e.stopPropagation(); ucpop.style.display = ucpop.style.display==='block' ? 'none' : 'block'; };
    document.addEventListener('click', (e)=>{ if (!ucpop.contains(e.target) && e.target!==ucbtn) ucpop.style.display='none'; });
  }
})();

/* path helper for detail pages */
function pathPart(i){ return decodeURIComponent(location.pathname.split('/').filter(Boolean)[i]||''); }
