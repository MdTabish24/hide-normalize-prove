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
