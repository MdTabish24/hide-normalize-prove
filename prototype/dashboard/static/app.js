'use strict';
let snapshot, active = 'isolation', selected, initialized = false;
const seen = new Set(), $ = id => document.getElementById(id);
const pct = n => typeof n === 'number' ? (n * 100).toFixed(1) + '%' : 'NOT RUN';
const sec = n => typeof n === 'number' ? n.toFixed(3) + 's' : 'NOT RUN';
const el = (tag, text, cls) => { const node = document.createElement(tag); if(text !== undefined) node.textContent = text; if(cls)node.className = cls; return node; };
function facts(target, pairs) { $(target).classList.remove('empty'); $(target).replaceChildren(...pairs.map(([k,v]) => {const box = el('div',undefined,'fact');box.append(el('span',k),el('strong',v ?? 'NOT RUN'));return box;})); }
function updatePair() {
  const rows = snapshot.live.requests, r = rows.find(r => r.index === selected) || rows.at(-1);
  if (!r) return;
  $('request-id').textContent = 'Request #' + r.index;
  const report = snapshot.live.report;
  facts('red', [['HTTP status',r.status],['Body shape',r.body_length + ' bytes'],['Time to first body byte',sec(r.ttfb)],['Total release time',sec(r.total)],['Submit response',r.response],['Headers',Object.entries(r.headers).map(([k,v])=>k+': '+v).join(' · ') || 'NOT RUN'],['Separate final report',report?report.safe_range.join(' – '):'NOT RUN'],['Report repeat / third read',report?`same: ${report.repeat_equal} · third pending: ${report.third_pending}`:'NOT RUN']]);
  facts('truth', [['Same request','#' + r.index],['Blue configuration',r.world],['Gateway outcome',r.allowed === 1 ? 'Allowed' : r.allowed === 0 ? 'Not allowed / no decision' : 'NOT RUN'],['Cancelled',r.cancelled === 1 ? 'Yes' : r.cancelled === 0 ? 'No' : 'NOT RUN'],['Actual compute duration',r.compute],['Model completion / score','NOT RUN']]);
}
function histogram(rows) {
  const canvas = $('histogram'), ctx = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
  ctx.clearRect(0,0,w,h);ctx.font='13px system-ui';ctx.fillStyle='#98afbd';
  rows = rows.filter(r => r.allowed !== null && typeof r.total === 'number');
  if (!rows.length) {ctx.fillText('NOT RUN · no paired HTTP observations and gateway outcomes',16,90);return;}
  const count = Math.max(10,Math.ceil(Math.max(...rows.map(r=>r.total))/.1)+1), bins = Array.from({length:count},()=>[0,0]);
  rows.forEach(r=>bins[Math.min(count-1,Math.floor(r.total/.1))][r.allowed===1?0:1]++);
  const max = Math.max(1,...bins.flat()), left=35, bottom=180, width=(w-55)/count;
  ctx.strokeStyle='#456171';ctx.beginPath();ctx.moveTo(left,15);ctx.lineTo(left,bottom);ctx.lineTo(w-10,bottom);ctx.stroke();
  bins.forEach((b,i)=>{b.forEach((n,j)=>{ctx.fillStyle=j===0?'#b8ed81':'#ffbf87';ctx.fillRect(left+i*width+j*width*.4+2,bottom-n/max*140,width*.36,n/max*140);});if(i%Math.max(1,Math.ceil(count/10))===0){ctx.fillStyle='#98afbd';ctx.fillText((i*.1).toFixed(1)+'s',left+i*width,202);}});
  ctx.fillStyle='#98afbd';ctx.fillText(String(max),6,40);ctx.fillText('0',12,bottom);
}
function table(headers, rows) {const t = el('table'),thead = el('thead'),tr=el('tr');headers.forEach(h=>tr.append(el('th',h)));thead.append(tr);t.append(thead);const body=el('tbody');rows.forEach(row=>{const r=el('tr');row.forEach(value=>r.append(el('td',value)));body.append(r);});t.append(body);return t;}
const captions = {isolation:'1 / Isolation · Red seedha Blue tak pahunch sakta hai?',audit:'2 / Prove · Log badlo, signature aur chain pakadte hain.',matrix:'3 / Measure · Jahan result nahi hai, saaf NOT RUN.',evidence:'4 / Evidence · Kya napa, kya abhi baaki hai.'};
function scenario() {
  if (!snapshot) return;
  document.querySelectorAll('[data-scenario]').forEach(b=>b.classList.toggle('active',b.dataset.scenario===active));
  $('caption').textContent=captions[active];const box=$('scenario-content');box.replaceChildren();
  if(active==='matrix') {
    const m=snapshot.matrix;box.append(el('p',`${m.saved}/${m.total} saved cells · audit ${m.audit?'enabled':'off / not recorded'} · scale ${m.scale??'NOT RUN'} · ${snapshot.label}`));
    box.append(table(['Cohort','Policy','Unseen accuracy','Wilson 95%','Test n','Train / gap'],m.rows.map(r=>[r.cohort,r.policy,r.status==='SAVED'?pct(r.accuracy):'NOT RUN',r.interval?r.interval.map(pct).join(' – '):'—',r.n??'—',r.status==='SAVED'?pct(r.train_accuracy)+' / '+pct(r.gap):'—'])));
    box.append(el('p','Interrupted matrix is incomplete. Cached in_progress does not mean a process is running.','fine'));
  } else if(active==='evidence') {
    const e=snapshot.evidence;box.append(el('p',e.note));box.append(e.rows.length?table(['Saved check','Recorded result','Recorded metric'],e.rows.map(r=>[r.test,r.result,r.metric||'—'])):el('p','NOT RUN'));
  } else {
    const s=snapshot.live.scenarios[active];box.append(el('p',`${active==='audit'?'Copy-only tamper demo on newly collected local gateway audit log':'Isolation demo inside the existing Red container'} · ${s.status}`));
    const b=el('button',active==='audit'?'Run copy-only audit demo':'Run 11 isolation checks');b.disabled=!canRun();b.onclick=()=>job(active);box.append(b);
    box.append(s.rows.length?table(['Case','Observed result'],s.rows.map(r=>[r.name,r.result])):el('p','NOT RUN · no fresh scenario result. Historical evidence is available in the Evidence table.'));
    if(active==='audit')box.append(el('p','Unmodified should be VALID; all seven edits INVALID. Collector is trusted. Checkpoint replacement / omissions before collection need an independent witness.','fine'));
  }
}
function canRun(){return snapshot?.live.worker_connected && !snapshot.live.matrix_active && snapshot.live.status!=='running';}
async function job(action) {
  $('message').textContent='Queueing a small explicit demo. No timing matrix is being started.';
  try {const response=await fetch('/api/jobs',{method:'POST',headers:{'content-type':'application/json','x-demo-ui':'1'},body:JSON.stringify({action,policy:$('policy').value,secret:$('secret').value})});const value=await response.json();$('message').textContent=value.reason||value.status;}catch{$('message').textContent='NOT RUN · operator connection unavailable';}
}
function render(data) {
  snapshot=data;const live=data.live;
  $('worker').textContent='Worker: '+(live.worker_connected?live.matrix_active?'BLOCKED · timing matrix active':live.status:'NOT RUN / disconnected');
  $('matrix-count').textContent=`Matrix: ${data.matrix.saved}/${data.matrix.total} saved`;
  $('measured-policy').textContent='Measured: '+live.policy+' · scale 0.1';
  $('warning').hidden=!data.test_only;$('policy').querySelector('[value="raw"]').disabled=!data.test_only;
  $('traffic').disabled=!canRun();
  if ($('message').textContent==='queued' || $('message').textContent.startsWith('Small demo')) {
    $('message').textContent=live.status==='running'?'Small demo running; saved matrix is unchanged.':live.status==='complete'?'Small demo complete. Results below are recorded observations.':live.status==='failed'?'NOT RUN / failed · check local prerequisites. No result asserted.':$('message').textContent;
  }
  const all=[...data.audit_events,...live.events];
  for(const lane of document.querySelectorAll('[data-lane]')) {
    const matches=all.filter(e=>e.lane===lane.dataset.lane),last=matches.at(-1);
    if(last){lane.querySelector('.lane-event').textContent=last.text+(last.request===null?'':' · '+last.request);if(initialized&&!seen.has(last.id)){lane.classList.remove('pulse');void lane.offsetWidth;lane.classList.add('pulse');const arrow=lane.nextElementSibling;if(arrow?.classList.contains('arrow')){arrow.classList.remove('pulse');void arrow.offsetWidth;arrow.classList.add('pulse');}}}
  }
  all.forEach(e=>seen.add(e.id));initialized=true;
  updatePair();histogram(live.requests);
  const a=live.accuracy;
  $('accuracy').textContent=a&&a.n?pct(a.correct/a.n):'NOT RUN';
  $('accuracy-note').textContent=a&&a.n?`${a.correct}/${a.n} held-out groups · Wilson 95% ${a.interval.map(pct).join(' – ')} · train n=${a.train_n}, accuracy ${pct(a.train_accuracy)}, gap ${pct(a.gap)}. Tiny illustrative sample.`:'Decision tree · HTTP features only · train/test groups separate.';
  const log=$('events');log.replaceChildren();
  live.requests.forEach(r=>{const b=el('button','#'+r.index+' · '+sec(r.total));b.onclick=()=>{selected=r.index;updatePair();};log.append(b);});
  all.slice(-20).reverse().forEach(e=>log.append(el('div',`${e.lane} · ${e.text} · ${e.source}`,'event-row')));
  if(!all.length)log.append(el('p','NOT RUN'));
  scenario();
}
document.querySelectorAll('[data-scenario]').forEach(b=>b.onclick=()=>{active=b.dataset.scenario;scenario();});
$('traffic').onclick=()=>job('traffic');$('presenter').onclick=()=>document.body.classList.toggle('presenting');
$('next').onclick=()=>{const order=Object.keys(captions);active=order[(order.indexOf(active)+1)%order.length];scenario();};
fetch('/api/snapshot').then(r=>r.json()).then(render).catch(()=>{$('connection').textContent='Disconnected';});
const stream=new EventSource('/api/events');stream.onopen=()=>{$('connection').textContent='SSE connected';};stream.onerror=()=>{$('connection').textContent='Reconnecting';};stream.onmessage=e=>render(JSON.parse(e.data));
