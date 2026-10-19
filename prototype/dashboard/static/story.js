'use strict';
var currentStory=null;
var byId=function(id){return document.getElementById(id);};
function render(data){
  currentStory=data;
  byId('connection').textContent=data.worker_connected?'Local demo ready':'Saved playback · worker offline';
  byId('record').disabled=!data.worker_connected||data.matrix_active||data.worker_status==='running';
  var r=data.requests.find(function(x){return x.blue==='NOT ALLOWED'&&x.output_contained===true;})||data.requests[0];
  var run=r?data.runs.find(function(x){return x.index===r.run;}):null;
  window.actorStage.setRecord(r,run);
  byId('proof-request').textContent=r?'#'+r.index+' · '+r.probe+' · '+r.blue:'NOT RUN';
  byId('proof-response').textContent=r?r.status+' / '+r.body_length+' bytes / '+r.response:'NOT RUN';
  byId('proof-audit').textContent=run?run.audit.status+' · '+run.audit.count+' events':'NOT RUN';
  byId('proof-report').textContent=run&&run.report.safe_range?run.report.safe_range.join(' – ')+' · budget '+run.report.budget_left+'/2':'NOT RUN';
  byId('proof-scope').textContent='Whole-run validity: '+data.validity.status+'. No matched Docker isolation or powered timing test for this four-request story.';
  byId('event-proof').textContent='event trail: '+data.events.length+' recorded controller events. Environment: '+data.environment+'. Playback is a simplified reconstruction from recorded facts, not original internal timing.';
  byId('record-status').textContent=data.worker_status==='running'?'Fresh test record ho raha hai…':data.worker_status==='failed'?'Recording failed; no new success asserted.':'Fresh recording optional hai. Upar ka button saved request samjhata hai.';
  window.storyReport.render(data);
}
byId('play').onclick=function(){window.actorStage.toggle();};
byId('record').onclick=async function(){
  if(window.actorStage.isPlaying()){byId('record-status').textContent='Pehle playback poora hone do.';return;}
  try{
    var response=await fetch('/api/jobs',{method:'POST',headers:{'content-type':'application/json','x-demo-ui':'1'},body:JSON.stringify({action:'story',policy:'bucket_hard',secret:'A'})});
    var value=await response.json();byId('record-status').textContent=value.reason||value.status;
  }catch(error){byId('record-status').textContent='Local server unavailable.';}
};
fetch('/api/story').then(function(r){return r.json();}).then(render).catch(function(){byId('connection').textContent='Local server offline';});
var updates=new EventSource('/api/story/events');
updates.onmessage=function(e){render(JSON.parse(e.data));};
updates.onerror=function(){byId('connection').textContent='Connection lost · saved view';};
