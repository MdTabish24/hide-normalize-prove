/* A simple explanatory replay built only from a recorded request. */
window.actorStage=(function(){
  var record=null,run=null,plan=[],index=0,timer=null,packetTimer=null,playing=false,paused=false,done=false;
  var el=function(id){return document.getElementById(id);};
  function clearEffects(){
    el('petals').replaceChildren();
    document.querySelectorAll('.shake').forEach(function(n){n.classList.remove('shake');});
    el('arena').classList.remove('packet-flying');
    clearTimeout(packetTimer);
  }
  function flowers(){
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    var colors=['#c9ee9b','#ffd4a5','#ffacbe','#b9d5ff'];
    for(var i=0;i<22;i++){
      var leaf=document.createElement('span');
      leaf.className='petal'+(i%4===0?' flower':'');
      leaf.style.setProperty('--x',(4+(i*43)%92)+'%');
      leaf.style.setProperty('--color',colors[i%4]);
      leaf.style.setProperty('--delay',((i%6)*.08)+'s');
      el('petals').append(leaf);
    }
  }
  function makePlan(r,audit){
    var blocked=r.blue==='NOT ALLOWED', allowed=r.blue==='ALLOWED';
    var steps=[
      {actor:'red',route:'send',title:'Red ne clue maanga.',copy:'Laal robot ne '+r.probe+' bheja.',speech:'Mujhe secret ka clue do!'},
      {actor:'gateway',route:'blue',title:'Gateway ne guard se check karaya.',copy:'Red seedha Blue ya model tak nahi jaata.',speech:'Pehle guard ka decision dekho.'},
      {actor:'blue',title:blocked?'Request ko aage nahi bheja gaya.':allowed?'Is request ko allow kiya gaya.':'Decision record nahi hua.',
       copy:blocked?'Gateway ne not-allowed save kiya.':allowed?'Allowed hona secret milna nahi hai.':'Is step ko pass nahi bol sakte.',speech:blocked?'Is request ko aage nahi jaana.':allowed?'Is request ko allow kiya gaya.':'Decision ka record nahi hai.'}
    ];
    steps.push(blocked?
      {actor:'red',effect:'shake',title:'Red ki yeh koshish ruk gayi.',copy:'Is baar model ko call nahi kiya gaya.',speech:'Meri request aage nahi pahunchi!'}:
      {actor:'model',route:allowed?'model':'',title:allowed?'Model wala rasta khula.':'Model ka result maloom nahi.',
       copy:'Abhi mock model hai. Actual generated answer save nahi hua.',speech:'Mera fixed setup: Dummy answer. Main real LLM nahi.'});
    steps.push({actor:'gateway',route:'return',title:r.output_contained===true?'Gateway ne raw jawab chhupa diya.':r.output_contained===false?'Reply ka check fail hua.':'Reply verify nahi hua.',
      copy:r.output_contained===true?'Actual response exact pending envelope tha.':'Expected pending envelope ka proof nahi.',
      speech:r.output_contained===true?'Raw answer nahi. Sirf pending.':'Is reply ko verified nahi bol sakta.',
      effect:r.output_contained===false?'shake':''});
    steps.push({actor:'red',title:'Red ko kya mila?',copy:'HTTP '+r.status+' · '+r.body_length+' bytes · '+r.response,
      speech:'Mujhe '+r.response+' mila. Raw model text nahi.'});
    steps.push({actor:'audit',route:'audit',title:audit&&audit.status==='VALID'?'Record ki jaanch bhi pass hui.':audit&&audit.status==='INVALID'?'Audit check fail hua.':'Audit ka proof abhi nahi hai.',
      copy:audit&&audit.status==='VALID'?audit.count+' events ka signed audit verify hua.':'Is record ko audit VALID nahi bolenge.',
      speech:audit&&audit.status==='VALID'?'Audit VALID · '+audit.count+' events':'Audit '+(audit?audit.status:'NOT RUN'),
      effect:audit&&audit.status==='INVALID'?'shake':''});
    steps.push({actor:'gateway',title:r.output_contained===true?'Jawab bacha!':r.output_contained===false?'Output gate check fail.':'Result abhi incomplete hai.',
      copy:r.output_contained===true?'PASS: Red ko raw model text nahi mila. Timing safety alag check hai.':'Missing ya failed check ko pass nahi bolenge.',
      speech:r.output_contained===true?'Is response mein raw jawab chhupa raha.':'Is response ka proof complete nahi.',
      effect:r.output_contained===true?'flowers':r.output_contained===false?'shake':'',result:r.output_contained===true?'success':r.output_contained===false?'failure':''});
    return steps;
  }
  function show(){
    clearEffects();
    var s=plan[index],arena=el('arena');
    arena.dataset.active=s.actor;arena.dataset.route=s.route||'';
    el('step-number').textContent=(index+1)+'/'+plan.length;
    el('narration-title').textContent=s.title;el('narration-copy').textContent=s.copy;
    el('narrator').className='narrator '+(s.result||'');
    el('speech-'+s.actor).textContent='“'+s.speech+'”';
    if(s.effect==='shake'){
      document.querySelectorAll('.actor-'+s.actor).forEach(function(n){n.classList.add('shake');});
      el('narrator').classList.add('shake');
    }
    if(s.effect==='flowers')flowers();
    if(s.route==='send'||s.route==='return'){
      arena.classList.add('packet-flying');
      var motion=el(s.route==='send'?'motion-send':'motion-return');
      if(motion&&motion.beginElement)motion.beginElement();
      packetTimer=setTimeout(function(){arena.classList.remove('packet-flying');},1000);
    }
  }
  function schedule(){
    timer=setTimeout(function(){
      if(!playing||paused)return;
      if(index===plan.length-1){
        playing=false;done=true;el('play').textContent='↻ Phir dekho';return;
      }
      index++;show();schedule();
    },2200);
  }
  function toggle(){
    if(!record)return;
    if(playing){
      paused=!paused;
      if(paused){clearTimeout(timer);el('arena').classList.remove('packet-flying');el('play').textContent='▶ Aage dekho';}
      else{el('play').textContent='Ⅱ Roko';schedule();}
      return;
    }
    plan=makePlan(record,run&&run.audit);index=0;done=false;paused=false;playing=true;
    el('play').textContent='Ⅱ Roko';show();schedule();
  }
  return {
    setRecord:function(r,matchedRun){
      if(playing)return;
      if(record&&r&&record.index===r.index&&record.total===r.total)return;
      record=r;run=matchedRun;done=false;
      clearEffects();el('arena').dataset.active='red';el('arena').dataset.route='';
      el('narrator').className='narrator';el('step-number').textContent='▶';
      el('narration-title').textContent=r?'Bas ek button dabao.':'Abhi recorded request nahi hai.';
      el('narration-copy').textContent=r?'Ek waqt par ek character. Aakhir mein clear result.':'Neeche proof section se fresh test record kar sakte ho.';
      el('play').textContent='▶ Demo dekho';el('play').disabled=!r;
    },
    toggle:toggle,
    isPlaying:function(){return playing;},
    comparisonData:function(data){
      var rows=data.matrix&&Array.isArray(data.matrix.rows)?data.matrix.rows:[];
      function cell(policy){return rows.find(function(r){return r.cohort==='ordinary'&&r.policy===policy&&r.status==='SAVED';})||null;}
      return {baseline:cell('raw'),protected:cell('bucket')};
    },
    makePlan:makePlan
  };
})();
