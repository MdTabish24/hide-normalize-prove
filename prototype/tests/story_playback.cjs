// Pure playback decisions; no browser, server, API calls or Node dependencies.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/static/stage.js'),'utf8'),context);
const stage=context.window.actorStage;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/static/report.js'),'utf8'),context);
const report=context.window.storyReport;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/static/scenes.js'),'utf8'),context);
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/static/duel.js'),'utf8'),context);
const duel=context.window.duelStory;
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../dashboard/static/story.js'),'utf8'),context);
const row={blue:'NOT ALLOWED',probe:'A-family probe',status:202,body_length:64,response:'pending',output_contained:true};

test('a stopped request never highlights a model call',()=>{
  const plan=stage.makePlan(row,{status:'VALID',count:19});
  assert.equal(plan.some(s=>s.actor==='model'),false);
  assert.equal(plan.some(s=>s.actor==='red'&&s.effect==='shake'),true);
  assert.equal(plan.at(-1).effect,'flowers');
  assert.match(plan.at(-1).copy,/Timing safety alag/);
});
test('an allowed request does not invent a model answer',()=>{
  const plan=stage.makePlan({...row,blue:'ALLOWED'},{status:'VALID',count:19});
  assert.equal(plan.some(s=>s.actor==='model'),true);
  assert.match(plan.find(s=>s.actor==='model').copy,/Actual generated answer save nahi/);
});
test('failed or missing envelope evidence never celebrates',()=>{
  for(const value of [false,null,undefined]){
    const plan=stage.makePlan({...row,output_contained:value},null);
    assert.notEqual(plan.at(-1).effect,'flowers');
  }
  assert.equal(stage.makePlan({...row,output_contained:false},null).at(-1).effect,'shake');
});
test('comparison uses recorded ordinary raw versus original bucket only',()=>{
  const rows=[{cohort:'ordinary',policy:'raw',status:'SAVED',accuracy:.985},
    {cohort:'ordinary',policy:'bucket',status:'SAVED',accuracy:.565},
    {cohort:'boundary',policy:'bucket',status:'SAVED',accuracy:1},
    {cohort:'ordinary',policy:'bucket_hard',status:'SAVED',accuracy:.9}];
  const result=stage.comparisonData({matrix:{rows}});
  assert.equal(result.baseline.accuracy,.985);
  assert.equal(result.protected.accuracy,.565);
  assert.equal(stage.comparisonData({}).protected,null);
});

test('full timing report preserves every expected arm and NOT RUN cells',()=>{
  const cohorts=['ordinary','boundary','overflow'];
  const rows=[];
  for(const policy of ['raw','bucket','bucket_hard','window_hard']){
    for(const cohort of cohorts)rows.push({cohort,policy,status:'NOT RUN'});
  }
  for(const policy of ['bucket_hard','window_hard']){
    for(const cohort of ['deadline_near','deadline_far'])rows.push({cohort,policy,status:'NOT RUN'});
  }
  Object.assign(rows[0],{status:'SAVED',accuracy:.985,n:200,interval:[.95,.99]});
  const result=report.matrixRows({matrix:{rows}});
  const values=result.flatMap(r=>r.slice(1));
  assert.equal(values.filter(v=>v.main==='NOT RUN').length,15);
  assert.equal(values.filter(v=>v.main==='—').length,4);
  assert.equal(values.find(v=>v.main==='98.5%').color,'bad');
});

test('complete report keeps failed checks and never passes absent report reads',()=>{
  const rows=report.evidenceRows({evidence:[{test:'Collector timing check (isolated host run)',status:'FAIL',metric:'',policy:'—',audit_mode:'on'},
    {test:'Attack suite',status:'NOT RUN',metric:'NOT RUN',policy:'—',audit_mode:'—'}]});
  assert.equal(rows[0][1].color,'bad');
  assert.equal(rows[1][1].main,'NOT RUN');
  const story=report.storyRows({runs:[{index:1,report:{},audit:{}}]});
  assert.equal(story[0][3].main,'NOT RUN');
  assert.equal(story[1][3].main,'NOT RUN');
  assert.equal(report.realRows({})[0][1],'NOT RUN');
});

test('paired playback separates Blue approval, model completion and Red envelope',()=>{
  const request={case:'blocked',status:202,body_length:64,total:.3,envelope_exact:true,
    trace:{blue_allowed:false,reason:'keyword_matched',model_called:false,model_completed:false}};
  const frames=duel.makeFrames({comparison:{arms:[{policy:'bucket_hard',requests:[request]}]}});
  const timing=frames.filter(f=>context.window.demoScenes.group(f)==='timing');
  assert.equal(timing[0].before.title,'NOT RUN');
  assert.match(timing[1].after.title,/blocks the request/);
  assert.match(timing[2].after.title,/never called/);
  assert.match(timing[3].after.result,/timing secrecy is not established/);
  assert.equal(frames.filter(f=>context.window.demoScenes.group(f)==='timing').length,16);
  assert.equal(frames.some(f=>f.case==='output'),false); // No invented real-provider example.
});

test('missing implementation remains explicit in coverage',()=>{
  assert.equal(duel.coverage.length,12);
  assert.equal(duel.coverage.some(r=>r[2].includes('attestation')),true);
  assert.equal(duel.coverage.some(r=>r[2].includes('Hosted KV reset')),true);
});

test('eight scenario families have visual scenes without invented baselines',()=>{
  const data={real_model:{example:{request_id:2,raw_excerpt:'saved quote',score:1,verdict:'PASS'},leaks:{}},
    individual_checks:[{group:'Isolation',test:'Direct blue-defense blocked',status:'PASS',observed:'PASS'},
      {group:'Audit tamper',test:'edit one event',status:'PASS',observed:'INVALID',expected:'INVALID'}]};
  const frames=duel.makeFrames(data);
  const groups=new Set(frames.map(context.window.demoScenes.group));
  assert.equal(groups.size,8);
  const isolation=frames.find(f=>f.case==='isolation');
  assert.equal(isolation.before.visual.type,'missing');
  assert.equal(isolation.after.visual.value,'BLOCKED');
  const audit=frames.find(f=>f.case==='audit');
  assert.equal(audit.after.visual.type,'audit');
  assert.equal(audit.after.visual.verifier,'INVALID');
  assert.equal(audit.after.visual.value,'TAMPER CAUGHT');
  const vault=frames.filter(f=>f.case==='vault');
  assert.equal(vault.some(f=>f.after.visual.value==='32 KiB RECORDS'),true);
});

test('fresh failed checks never fall back to historical passes',()=>{
  const historical={individual_checks:[{group:'Isolation',test:'Docker socket absent',status:'PASS',observed:'PASS'},
    {group:'Audit tamper',test:'edit one event',status:'PASS',observed:'INVALID',expected:'INVALID'}]};
  const frames=duel.makeFrames({...historical,scenarios:{isolation:{recorded_at:123,rows:[]},audit:{recorded_at:123,rows:[]}}});
  for(const group of ['isolation','audit']){
    const current=frames.filter(f=>f.case===group);
    assert.equal(current.length,1);
    assert.match(current[0].source,/LATEST OPERATOR RUN.*NO RESULT/);
    assert.equal(current[0].after.visual.type,'missing');
  }
});

test('only supported live scenarios can submit jobs; real-model evidence stays offline',()=>{
  const live=context.window.liveDemo;
  assert.equal(live.actionFor('timing'),'comparison');
  assert.equal(live.actionFor('feedback'),'controls');
  assert.equal(live.actionFor('audit'),'controls');
  assert.equal(live.actionFor('isolation'),'isolation');
  assert.equal(live.actionFor('leakage'),'traffic');
  assert.equal(live.actionFor('output'),null);
  assert.equal(live.actionFor('vault'),'controls');
  assert.match(live.hint('output'),/not rerun here/);
});

test('real-model view uses measured operator output and never invents a completion',()=>{
  const absent=duel.makeFrames({}).filter(f=>f.case==='real');
  assert.equal(absent.length,1);assert.equal(absent[0].after.title,'NOT RUN');
  const frames=duel.makeFrames({real_run:{status:'complete',recorded_at:123,audit:'VALID',requests:[{
    case:'allowed',answer:'Live answer fixture',backend:'DeepSeek',model:'deepseek-flash',
    status:202,body_length:64,total:3.1,envelope_exact:true}]}}).filter(f=>f.case==='real');
  assert.equal(frames.length,4);
  assert.equal(frames[2].before.copy,'Live answer fixture');
  assert.equal(frames[3].after.facts.model,'Raw text withheld');
  assert.deepEqual(Array.from(frames[3].headings),['Trusted operator sees','Red receives']);
});

test('fresh tiny A/B run does not borrow old matrix results or invent a baseline',()=>{
  const frames=duel.makeFrames({job:{action:'traffic',finished_at:123},worker_status:'complete',
    test_sample:{correct:2,n:4,train_n:4},matrix:{saved:6,total:16,rows:[{cohort:'ordinary',policy:'raw',status:'SAVED',accuracy:.985,n:200}]}});
  const measured=frames.filter(f=>f.case==='leakage');
  assert.equal(measured.length,1);
  assert.equal(measured[0].before.visual.type,'missing');
  assert.equal(measured[0].after.visual.value,'50.0%');
  assert.match(measured[0].source,/LATEST OPERATOR RUN/);
  assert.match(measured[0].after.result,/tiny sample/);
});

test('completed measured controls replace absent baselines with actual comparisons',()=>{
  const controls=JSON.parse(fs.readFileSync(path.join(__dirname,'../evidence/controls-comparison.json'),'utf8'));
  const frames=duel.makeFrames({controls}).filter(f=>['vault','audit','feedback'].includes(f.case));
  assert.equal(frames.length,16);
  assert.equal(frames.some(f=>f.before.visual.type==='missing'),false);
  assert.equal(frames.find(f=>f.case==='vault').before.visual.value,'PAYLOAD FOUND');
  assert.equal(frames.find(f=>f.case==='vault').after.visual.value,'SEALED');
  const changed=frames.find(f=>f.question==='edit one event');
  assert.equal(changed.before.visual.value,'ACCEPTED AS JSON');
  assert.equal(changed.after.visual.value,'INVALID');
  assert.match(changed.scope[0],/Deliberately no integrity checks/);
  const budget=frames.find(f=>f.question==='Third read and process restart');
  assert.equal(budget.after.visual.value,'BOTH WITHHELD');
  assert.deepEqual(Array.from(budget.headings),['Trusted evaluator','Red receives']);
});

test('failed controls never display old successful measurements',()=>{
  const controls={status:'failed',recorded_at:123,vault:{plaintext_found:true,ciphertext_found:false,roundtrip:true}};
  const frames=duel.makeFrames({controls}).filter(f=>['vault','audit','feedback'].includes(f.case));
  assert.equal(frames.length,3);
  assert.equal(frames.every(f=>f.before.visual.type==='missing'&&f.after.visual.type==='missing'),true);
});

test('a fresh tiny leakage sample does not erase measured controls',()=>{
  const controls=JSON.parse(fs.readFileSync(path.join(__dirname,'../evidence/controls-comparison.json'),'utf8'));
  const frames=duel.makeFrames({controls,job:{action:'traffic',finished_at:123},worker_status:'complete',test_sample:{correct:2,n:4,train_n:4}});
  assert.equal(frames.filter(f=>f.case==='audit').length,8);
  assert.equal(frames.filter(f=>f.case==='vault').length,4);
});
