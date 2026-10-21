'use strict';
var el=id=>document.getElementById(id);
function render(data){
  el('connection').textContent=data.worker_connected?'Local worker connected • tables show saved evidence':'Saved evidence • worker offline';
  el('record').disabled=!data.worker_connected||data.matrix_active||data.worker_status==='running';
  el('record-status').textContent=data.worker_status==='running'?'Recording paired mock requests…':data.worker_status==='failed'?'Recording failed; no new success asserted.':'Optional: playback does not start an evaluation.';
  window.storyReport.render(data);
  var fragment=document.createDocumentFragment();
  window.demoScenes.coverage.forEach(function(row){var tr=document.createElement('tr');row.forEach(function(value,i){var td=document.createElement(i===0?'th':'td');td.textContent=value;if(i===0)td.scope='row';tr.append(td);});fragment.append(tr);});
  el('coverage-results').replaceChildren(fragment);
}
fetch('/api/story').then(r=>r.json()).then(render).catch(()=>el('connection').textContent='Server unavailable');
var updates=new EventSource('/api/story/events');updates.onmessage=e=>render(JSON.parse(e.data));
el('record').onclick=async function(){
  try{var response=await fetch('/api/jobs',{method:'POST',headers:{'content-type':'application/json','x-demo-ui':'1'},body:JSON.stringify({action:'comparison',policy:'bucket_hard',secret:'A'})});var value=await response.json();el('record-status').textContent=value.reason||value.status;}
  catch(error){el('record-status').textContent='Local server unavailable';}
};
