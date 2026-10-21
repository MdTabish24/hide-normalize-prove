'use strict';
var el=id=>document.getElementById(id);
var GOOD=['PASS','BLOCKED','VALID','NO LEAK FOUND'],BAD=['FAIL','LEAKED','INVALID'];
function pill(r){var s=document.createElement('span');s.className='result-pill '+(GOOD.includes(r)?'good':BAD.includes(r)?'bad':'waiting');s.textContent=r;return s;}
function cell(tag,v){var c=document.createElement(tag);if(v instanceof Node)c.append(v);else c.textContent=v;return c;}
function stack(map){var d=document.createElement('div');Object.keys(map).forEach(function(k){var line=document.createElement('div');line.append(document.createTextNode((k==='ours'?'':k+': ')+map[k].value+' '),pill(map[k].verdict));d.append(line);});return d;}
function fill(id,rows){el(id).replaceChildren(...rows);}
function render(d){
  el('note').textContent=d.note;
  fill('steps',d.steps.map(function(s){var tr=document.createElement('tr');tr.append(cell('td',s.n+'. '+s.what),cell('td',s.how),cell('td',s.control),cell('td',s.result==='—'?'—':pill(s.result)));return tr;}));
  fill('channels',d.channels.map(function(c){var tr=document.createElement('tr');var b=document.createElement('div');b.append(document.createTextNode(c.baseline.value+' '),pill(c.baseline.verdict));
    tr.append(cell('th',c.channel),cell('td',b),cell('td',c.baseline_why),cell('td',stack(c.ours)),cell('td',c.ours_why));return tr;}));
  fill('policies',d.policies.map(function(p){var tr=document.createElement('tr');
    tr.append(cell('th',p.policy),cell('td',pill(p.verdict)),cell('td',p.failed.length?p.failed.join(' · '):p.missing.length?'(none failed) not measured: '+p.missing.join(' · '):'none'),cell('td',p.uncertain.join(' · ')||'—'),cell('td',p.passed.join(' · ')||'—'),cell('td',p.usability+(p.unusable.length?' · NOT usable in: '+p.unusable.join(', '):'')));return tr;}));
  fill('costs',d.costs.map(function(r){var tr=document.createElement('tr');
    tr.append(cell('th',r.policy),cell('td',r.cohort),cell('td',r.completed+'%'),cell('td',r.cancelled+'%'+(r.raw_value>100?' (stored value '+r.raw_value+'%, counting quirk unverified)':'')),cell('td',r.latency+' s'),cell('td',r.added===null?'—':'+'+r.added+' s'),cell('td',pill(r.usable==='YES'?'PASS':'FAIL')));return tr;}));
  el('validity').textContent='This run: '+d.validity.status+'. '+d.validity.reason+' (timing matrix saved: '+d.matrix_saved+' of '+d.matrix_total+' cells)';
  fill('checks',d.checks.map(function(c){var tr=document.createElement('tr');tr.append(cell('td',c.check),cell('td',pill(c.result)));return tr;}));
  fill('uncovered',d.not_covered.map(function(c){var tr=document.createElement('tr');tr.append(cell('th',c.channel),cell('td',c.note));return tr;}));
}
fetch('/api/why').then(r=>r.json()).then(render).catch(()=>el('note').textContent='Server unavailable');
