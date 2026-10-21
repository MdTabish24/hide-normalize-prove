'use strict';
// Only these existing operator actions can run. Playback never submits a job.
window.liveDemo={
  actionFor:function(group){return {real:'real',timing:'comparison',isolation:'isolation',vault:'controls',feedback:'controls',audit:'controls',leakage:'traffic'}[group]||null;},
  hint:function(group){return {
    timing:'Fresh HTTP comparison: raw timing vs bucket_hard. Both retain other controls. Mock model.',
    real:'Real DeepSeek through the local gateway. Requires DEEPSEEK_API_KEY in the launching terminal. No mock fallback. Two probes; at most 4 provider calls including retries.',
    isolation:'Runs actual probes inside the existing Docker red-client. Docker stack must be running.',
    feedback:'Measures exact evaluator count vs Red range, repeat reads and budget after a process restart. Also checks vault and audit. Mock model.',
    audit:'Measures JSON-only reading vs signed verification on the same eight original/tampered copies. Also checks vault and reports.',
    leakage:'Tiny A/B smoke test: 4 training + 4 unseen groups. Not the full matrix. Mock model.',
    output:'Saved DeepSeek extraction evidence only. Use Live DeepSeek for a fresh pipeline test; this extraction batch is not rerun here.',
    vault:'Measures plaintext vs AES-GCM on dummy files, fixed record sizes, and role access over real local HTTP. Also checks audit and reports. No provider key needed.'
  }[group]||'Choose a scenario.';}
};
if(typeof document!=='undefined'){
  let snapshot=null,pending=null,lastMessage='',failedGroup=null;
  const $=id=>document.getElementById(id);
  function controls(){
    const group=$('scenario').value,action=window.liveDemo.actionFor(group),busy=!!pending||(snapshot&&snapshot.worker_status==='running');
    $('run-live').disabled=!action||!snapshot||!snapshot.worker_connected||snapshot.matrix_active||busy||(group==='real'&&!snapshot.real_provider_available);
    $('run-live').textContent=busy?'Test running…':'Run test now';
    $('scenario').disabled=busy;
    if(busy){$('play').disabled=true;$('next').disabled=true;}
    document.querySelector('.duel-stage').hidden=busy||failedGroup===group;
    $('live-status').dataset.busy=busy?'true':'false';
    $('live-status').textContent=busy?(pending&&pending.job_id&&snapshot&&snapshot.job&&snapshot.job.id===pending.job_id?
      'RUNNING · actual local test · waiting for measured results…':'QUEUED · waiting for the local operator…'):
      lastMessage||(!snapshot||!snapshot.worker_connected?'Operator disconnected. Tests cannot run. ':snapshot.matrix_active?'Timing evaluation active. Demo actions paused. ':'')+window.liveDemo.hint(group);
  }
  $('play').onclick=()=>window.duelStory.toggle();
  $('next').onclick=()=>window.duelStory.next();
  $('scenario').onchange=e=>{lastMessage='';failedGroup=null;window.duelStory.select(e.target.value);controls();};
  $('run-live').onclick=async function(){
    const group=$('scenario').value,action=window.liveDemo.actionFor(group);
    if(!action||this.disabled)return;
    window.duelStory.stop();pending={group:group,job_id:null};lastMessage='';failedGroup=null;controls();
    try{
      const response=await fetch('/api/jobs',{method:'POST',headers:{'content-type':'application/json','x-demo-ui':'1'},
        body:JSON.stringify({action:action,policy:'bucket_hard'})});
      const result=await response.json();
      if(!response.ok||result.status!=='queued'||!result.job_id)throw new Error(result.reason||'Operator rejected the test.');
      pending.job_id=result.job_id;controls();
    }catch(error){pending=null;failedGroup=group;lastMessage='NOT RUN · '+error.message;controls();}
  };
  function render(data){
    snapshot=data;
    if(!pending)window.duelStory.update(data);
    else if(pending.job_id&&data.job&&data.job.id===pending.job_id&&data.job.finished_at){
      const group=pending.group;pending=null;
      window.duelStory.update(data);window.duelStory.select(group);
      if(data.worker_status==='complete'){
        failedGroup=null;lastMessage='TEST FINISHED · '+new Date(data.job.finished_at*1000).toLocaleTimeString()+' · playing its measured results below.';
        window.duelStory.toggle();
      }else{failedGroup=group;lastMessage='NO COMPLETE RESULT · test '+data.worker_status+'. Previous evidence is not a fresh pass.';}
    }else if(!data.worker_connected){
      failedGroup=pending.group;pending=null;lastMessage='NO COMPLETE RESULT · operator disconnected during the test.';
    }
    controls();
  }
  fetch('/api/story').then(r=>r.json()).then(render).catch(()=>{
    $('duel-source').textContent='Server unavailable';$('live-status').textContent='Server unavailable. No test is running.';
  });
  const updates=new EventSource('/api/story/events');
  updates.onmessage=e=>render(JSON.parse(e.data));
  updates.onerror=()=>{$('live-status').textContent='Connection lost. Reconnecting; no completed result asserted.';};
}
