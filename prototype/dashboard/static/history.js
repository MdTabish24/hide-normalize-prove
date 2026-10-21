'use strict';
var el=id=>document.getElementById(id);
function pill(result){var s=document.createElement('span');s.className='result-pill '+(result==='PASS'?'good':result==='FAIL'?'bad':'waiting');s.textContent=result;return s;}
function cell(tag,content){var c=document.createElement(tag);if(content instanceof Node)c.append(content);else c.textContent=content;return c;}
function show(row){
  el('detail').hidden=false;
  el('d-title').textContent=row.title;el('d-explains').textContent=row.explains;
  el('d-verdict').textContent=(row.verdict||'')+(row.checked_at?' · checked '+row.checked_at:'');
  el('d-details').replaceChildren(...(row.details||[]).map(t=>{var li=document.createElement('li');li.textContent=t;return li;}));
  el('d-meta').textContent=row.sha256?('File '+row.file+' · '+row.bytes+' bytes · SHA-256 '+row.sha256+' · date from '+row.recorded_source+(row.first_seen?' · first seen '+row.first_seen:'')):'No saved file.';
  el('detail').scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function recheck(id,button){
  button.disabled=true;
  try{var r=await fetch('/api/history/recheck',{method:'POST',headers:{'content-type':'application/json','x-demo-ui':'1'},body:JSON.stringify({id:id})});
    if(!r.ok)throw new Error();show(await r.json());}
  catch(e){el('d-verdict').textContent='Recheck unavailable; nothing asserted.';el('detail').hidden=false;}
  button.disabled=false;
}
function render(data){
  el('note').textContent=data.note;
  var fragment=document.createDocumentFragment();
  data.entries.forEach(function(row){
    var tr=document.createElement('tr');
    var button=document.createElement('button');button.textContent='Recheck';button.onclick=()=>recheck(row.id,button);
    tr.append(cell('td',row.recorded_at||'—'),cell('th',row.title),cell('td',pill(row.result)),
      cell('td',row.headline+(row.changed_since_first_seen?' · FILE CHANGED SINCE FIRST SEEN':'')),cell('td',button));
    tr.firstChild.nextSibling.scope='row';fragment.append(tr);
  });
  el('rows').replaceChildren(fragment);
}
fetch('/api/history').then(r=>r.json()).then(render).catch(()=>el('note').textContent='Server unavailable');
