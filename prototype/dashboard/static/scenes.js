/* Visual scenes project saved evidence. Unmeasured baselines remain unmeasured. */
window.demoScenes=(function(){
  var options=[['real','Live DeepSeek'],['timing','Response timing'],['output','Output disclosure'],['isolation','Network isolation'],
    ['vault','Vault & identity'],['feedback','Final report & budget'],['audit','Audit tampering'],['leakage','Secret A/B evaluation']];
  var coverage=[
    ['Encrypted payload vault','IMPLEMENTED','Blue config, Red prompts and model outputs are AES-GCM sealed; private artifacts require evaluator + finished run.'],
    ['Fixed-size records & dummy reads','PARTIAL','32 KiB encrypted records and cover reads. Filenames, counts and host access patterns are not hidden; not ORAM.'],
    ['Role & workload identity','PARTIAL','Token-derived roles exist. Workload attestation is missing.'],
    ['Timing policies','IMPLEMENTED','Four policies exist; default bucket_hard still exposes bucket boundaries.'],
    ['Error normalization','PARTIAL','Same status/body; default error release can differ from normal replies.'],
    ['Cache isolation','PARTIAL','Mock role/run namespaces; real adapter uses fresh salted requests. Hosted KV reset is not controlled.'],
    ['Output mediation','IMPLEMENTED','Raw text withheld. Live final reports are ranges; real score-only comparison is offline.'],
    ['Noisy ranges & budgets','IMPLEMENTED','Stable range, two reads/run, 100 submissions/run. Heuristic, not differential privacy.'],
    ['Fresh model session','PARTIAL','Real adapter sends no history, tools or shared conversation. Provider KV lifecycle remains outside our control.'],
    ['Leakage measurement','PARTIAL','Separate train/test runs; only 6/16 matrix cells are saved.'],
    ['Signed audit','IMPLEMENTED','Hash chain, count/bytes and Ed25519 checkpoints. No independent witness.'],
    ['Complete isolation proof','INCOMPLETE','Hardware, host escape, UI access and bidirectional confidentiality remain unproved.']
  ];
  function side(actor,title,copy,value,detail,result,tone,type){
    return {actor:actor,title:title,copy:copy,facts:{blue:'—',model:'—',red:'—'},result:result||'',tone:tone||'',
      visual:{type:type||'shield',value:value,detail:detail||'',state:tone||'waiting'}};
  }
  function missing(){return side('none','Baseline not recorded','No unprotected deployment result was measured.','NOT MEASURED','','No comparison claim','waiting','missing');}
  function frame(id,title,question,source,after,phase){
    return {case:id,chapter:title,question:question,source:source,phase:phase||0,before:missing(),after:after,
      labels:['Target / private state','Defense / verification','Observed result']};
  }
  function measuredControls(data){
    var c=data.controls;if(!c||!['complete','failed','running'].includes(c.status))return [];
    var out=[],source=(c.origin==='saved evidence'?'SAVED MEASURED CONTROLS':'MEASURED LOCAL CONTROLS')+' · '+new Date(c.recorded_at*1000).toLocaleTimeString()+' · dummy data / mock backend';
    if(c.status!=='complete')return ['vault','feedback','audit'].map(function(group){
      var f=frame(group,'Control comparison incomplete','No completed measurement',source+' · '+c.status.toUpperCase(),missing(),0);
      f.headings=['No complete baseline','No complete protected result'];return f;
    });
    function pair(group,title,left,right,headings,scope,note){
      out.push({case:group,phase:out.filter(f=>f.case===group).length,chapter:title,question:title,
        source:source,before:left,after:right,headings:headings,scope:scope,measured:true,note:note,
        labels:['Private state','Control tested','Observed result']});
    }
    function result(actor,title,copy,value,ok,type){
      var s=side(actor,title,copy,value,'',ok===true?'CONTROL CHECK PASSED':ok===false?'CHECK FAILED':'DIAGNOSTIC BASELINE',
        ok===true?'good':ok===false?'bad':'waiting',type);
      s.facts={blue:title,model:copy,red:value};return s;
    }
    var v=c.vault||{},id=c.identity||{},fb=c.feedback||{};
    var vaultScope=['Temporary plaintext copy of dummy payload','Same dummy payload through the production vault class'];
    var vaultNote='Local file experiment. Not ORAM: counts, filenames and host access patterns remain visible.';
    pair('vault','Can a file reader find the payload?',
      result('red','Read the plaintext copy','Exact marker scan of the file bytes',v.plaintext_found===true?'PAYLOAD FOUND':'CHECK FAILED',null,'vault'),
      result('gateway','Read the encrypted record','Marker scan plus authorized decrypt round-trip',v.ciphertext_found===false&&v.roundtrip===true?'SEALED':'CHECK FAILED',v.ciphertext_found===false&&v.roundtrip===true,'vault'),
      ['Plaintext storage','AES-GCM vault'],vaultScope,vaultNote);
    pair('vault','Does payload length change record size?',
      result('red','Compare two plaintext files','Short and long dummy values',(v.plain_sizes||[]).join(' / ')+' bytes',null,'vault'),
      result('gateway','Compare their encrypted records','Two reads from disk',(v.sealed_sizes||[]).join(' / ')+' bytes',
        v.sealed_sizes&&v.sealed_sizes.length===2&&v.sealed_sizes.every(n=>n===32768),'vault'),
      ['Plaintext storage','Padded encrypted storage'],vaultScope,vaultNote);
    pair('vault','Can another owner decrypt the record?',
      result('gateway','Correct owner binding','Authenticated decrypt of both dummy values',v.roundtrip===true?'DECRYPTED':'CHECK FAILED',v.roundtrip,'identity'),
      result('red','Changed owner binding','Same ciphertext and key; different authenticated owner',v.wrong_binding_denied===true?'DECRYPT REJECTED':'CHECK FAILED',v.wrong_binding_denied,'identity'),
      ['Correct owner','Wrong owner'],['Actual authenticated decrypt','Actual AES-GCM authentication failure'],vaultNote);
    var denied=id.red_pending===true&&id.blue_pending===true&&id.bad_token_pending===true;
    pair('vault','Who can fetch completed private artifacts?',
      result('gateway','Evaluator HTTP request','After run finish',typeof id.evaluator_records==='number'?id.evaluator_records+' records':'NO RESULT',typeof id.evaluator_records==='number'&&id.evaluator_records>0,'identity'),
      result('red','Red, Blue and bad-token HTTP requests','Same private-artifact endpoint',denied?'ALL PENDING':'CHECK FAILED',denied,'identity'),
      ['Authorized evaluator','Unauthorized callers'],['Same protected deployment · local HTTP','Measured status, headers and exact 64-byte body'],
      'Token-derived roles are tested. Workload attestation is not implemented.');
    var exact=typeof fb.true_count==='number'?String(fb.true_count)+' SAFE':'NO RESULT';
    [
      ['Before run completion',fb.before_pending===true?'PENDING':'CHECK FAILED',fb.before_pending],
      ['After run completion',Array.isArray(fb.safe_range)?fb.safe_range.join('–')+' SAFE':'NO RESULT',typeof fb.true_count==='number'&&Array.isArray(fb.safe_range)&&fb.safe_range[0]<=fb.true_count&&fb.true_count<=fb.safe_range[1]],
      ['Repeat the same report',fb.repeat_equal===true?'SAME RANGE':'CHECK FAILED',fb.repeat_equal],
      ['Third read and process restart',fb.third_pending===true&&fb.restart_pending===true?'BOTH WITHHELD':'CHECK FAILED',fb.third_pending===true&&fb.restart_pending===true]
    ].forEach(function(r){
      pair('feedback',r[0],result('gateway','Evaluator ground truth','Exact count from evaluator-only HTTP endpoint',exact,null,'feedback'),
        result('gateway','Red report endpoint',r[0],r[1],r[2],'feedback'),
        ['Trusted evaluator','Red receives'],['Private diagnostic reference; not an exposed Red baseline','Same protected run · actual HTTP report reads'],
        'Heuristic protection, not differential privacy. Fresh-run averaging and extreme counts can still reveal information.');
    });
    (c.audit||[]).forEach(function(r){
      var clean=r.case==='unmodified',ok=r.signed_valid===(clean?true:false),known=typeof r.signed_valid==='boolean';
      var before=result('red','Read the log as JSON',r.case,r.json_readable===true?'ACCEPTED AS JSON':'UNREADABLE',null,'audit');
      before.tone=clean||r.json_readable!==true?'waiting':'bad';before.visual.state=before.tone;before.result=r.json_readable!==true?'JSON READING FAILED':clean?'READABLE ORIGINAL':'TAMPERING STILL READABLE';
      var after=result('gateway','Run signed verification',r.case,known?(r.signed_valid?'VALID':'INVALID'):'NO RESULT',ok,'audit');
      after.visual.verifier=known?(r.signed_valid?'VALID':'INVALID'):'NOT RUN';
      if(ok&&!clean){after.actor='red';after.effect='shake';after.result='TAMPER DETECTED';}
      pair('audit',r.case,before,after,['JSON reading only','Signed audit verifier'],
        ['Deliberately no integrity checks; actual copied log','Same copied log + checkpoint; actual verifier'],
        'Diagnostic comparison, not an insecure deployment. Collector and pinned public key are trusted; pre-collection omissions cannot be detected.');
    });
    return out;
  }
  function additional(data){
    var out=[],checks=data.individual_checks||[];
    var scenarios=data.scenarios||{};
    function latest(name,group){
      var s=scenarios[name];
      if(!s||typeof s.recorded_at!=='number')return checks.filter(r=>r.group===group);
      return (s.rows||[]).map(r=>{var expected=group==='Audit tamper'?(r.name==='unmodified'?'VALID':'INVALID'):'PASS';
        return {group:group,test:r.name,observed:r.result,expected:expected,status:r.result==='NOT RUN'?'NOT RUN':r.result===expected?'PASS':'FAIL'};});
    }
    function provenance(name,fallback){var s=scenarios[name];return s&&typeof s.recorded_at==='number'?
      'LATEST OPERATOR RUN · '+new Date(s.recorded_at*1000).toLocaleTimeString()+' · '+(name==='audit'?'fresh signed log; tampered copies':'actual Docker probes'):fallback;}
    var real=data.real_model||{},latency=real.metrics||{};
    if(typeof latency.p50_seconds==='number'&&!(data.comparison&&data.comparison.origin==='operator run')){
      var summary=[latency.p50_seconds,latency.p95_seconds,latency.p99_seconds].map(x=>typeof x==='number'?x.toFixed(2):'?').join(' / ')+'s';
      var raw=side('model','Measured real-model latency','No padding applied to these measurements.',summary,'p50 / p95 / p99','REAL RESPONSE TIMES','waiting','latency');
      raw.visual.progress=Math.min(1,latency.p99_seconds/3);raw.facts={blue:'No A/B secret labels',model:real.provider,red:summary};
      var padded=side('gateway','The latency cost of padding','The padding was replayed offline.',
        typeof latency.mean_added_latency_seconds==='number'?'+'+latency.mean_added_latency_seconds.toFixed(2)+'s':'NOT RUN',
        'Mean added latency · '+(typeof latency.overrun_rate_past_3s==='number'?(latency.overrun_rate_past_3s*100).toFixed(1)+'% above 3s':'overrun not recorded'),
        'OFFLINE PADDING COST','waiting','latency');
      padded.visual.progress=typeof latency.mean_added_latency_seconds==='number'?latency.mean_added_latency_seconds/3:0;
      out.push({case:'timing_real',phase:3,chapter:'Real latency & padding cost',question:'How much waiting does normalization add?',
        source:'Real '+real.provider+' run · n='+real.n+' · small sample · offline padding',before:raw,after:padded,
        note:'Real measured latencies; offline padding. This is not an A/B secrecy test.',scope:['Measured API latency','Offline bucket padding']});
    }
    var isolation=latest('isolation','Isolation');
    isolation.forEach(function(r,i){
      var passed=r.status==='PASS';
      var observed=passed?(r.test==='Gateway submit is 202 pending'?'202 PENDING':r.test==='Red defense request is generic'?'GENERIC REPLY':r.test==='Docker socket absent'?'ABSENT':'BLOCKED'):r.status;
      var a=side('gateway',passed?'Boundary held':r.status==='FAIL'?'Isolation check failed':'No saved result',
        r.test,observed,'Docker check '+(i+1)+'/11',passed?'EXPECTED RESULT':'NOT VERIFIED',passed?'good':r.status==='FAIL'?'bad':'waiting','network');
      a.facts={blue:r.test,model:'Private networks',red:r.observed};
      if(passed&&observed!=='202 PENDING'){a.actor='red';a.effect='shake';}
      out.push(frame('isolation','Network isolation',r.test,provenance('isolation','Historical Docker evidence · not a fresh health check'),a,3));
    });
    if(!isolation.length)out.push(frame('isolation','Network isolation','Can Red bypass the gateway?',provenance('isolation','No saved isolation evidence')+' · NO RESULT',missing(),3));
    [
      ['Red / Blue / model payloads','SEALED','AES-GCM encryption at rest','Prompts, Blue config and outputs; gateway-only data volume.','vault','good'],
      ['Role authentication','TOKEN CHECK','The token determines the role','Workload identity is still missing.','identity','waiting'],
      ['Storage padding','32 KiB RECORDS','Fixed-size encrypted records + cover reads','Counts, filenames and host access patterns remain visible; not ORAM.','vault','waiting'],
      ['Hosted KV reset','NOT CONTROLLED','Stateless messages + fresh nonce','Provider cache deletion is not available or verified.','vault','waiting']
    ].forEach(function(r,i){
      var a=side('gateway',r[0],r[3],r[1],r[2],r[1],r[5],r[4]);
      a.facts={blue:r[0],model:r[2],red:r[3]};
      out.push(frame('vault','Vault & identity',r[0],'Code inspection & selected unit tests · not a paired attack run',a,i));
    });
    var run=(data.runs||[])[0],report=run&&run.report||{};
    var range=Array.isArray(report.safe_range)?report.safe_range.join('–'):'NOT RUN';
    [
      ['Run completed',range,'A range replaces the exact safe count.',Array.isArray(report.safe_range),'Report range'],
      ['Read the same report again',report.repeat_equal===true?'SAME RANGE':'NOT VERIFIED','The range is stored per run.',report.repeat_equal===true,'Stable repeat'],
      ['Read a third time',report.third_pending===true?'WITHHELD':'NOT VERIFIED','The two-read budget is exhausted.',report.third_pending===true,'Read budget'],
      ['Privacy boundary','HEURISTIC ONLY','Fresh-run averaging and extreme counts remain risks.',false,'Not differential privacy']
    ].forEach(function(r,i){
      var a=side('gateway',r[0],r[2],r[1],r[4],r[3]?'CHECK PASSED':'LIMITATION',r[3]?'good':'waiting','feedback');
      a.facts={blue:'Exact count stays evaluator-side',model:'Budget left: '+(typeof report.budget_left==='number'?report.budget_left+'/2':'NOT RUN'),red:r[1]};
      if(i===2&&r[3]){a.actor='red';a.effect='shake';}
      out.push(frame('feedback','Final report & budget',r[0],(data.recorded_at?'Measured HTTP run · '+new Date(data.recorded_at*1000).toLocaleTimeString():'No report test recorded')+' · mock model',a,i));
    });
    var audit=latest('audit','Audit tamper');
    audit.forEach(function(r,i){
      var passed=r.status==='PASS',clean=r.test==='unmodified';
      var a=side('gateway',clean?'Original log verified':passed?'Tampering detected':'Verification incomplete',r.test,
        passed?(clean?'LOG INTACT':'TAMPER CAUGHT'):r.observed,'Verifier: '+r.observed,
        passed?(clean?'VALID ORIGINAL':'TAMPER DETECTED'):r.status,passed?'good':r.status==='FAIL'?'bad':'waiting','audit');
      a.visual.verifier=r.observed;
      a.facts={blue:r.test,model:'Expected: '+r.expected,red:'Verifier: '+r.observed};
      if(passed&&!clean){a.actor='red';a.effect='shake';}
      out.push(frame('audit','Audit tampering',r.test,provenance('audit','Historical signed-log verification · copies only'),a,i%4));
    });
    if(!audit.length)out.push(frame('audit','Audit tampering','Alter the log',provenance('audit','No saved audit cases')+' · NO RESULT',missing(),3));
    var sample=data.test_sample,job=data.job;
    if(job&&job.action==='traffic'&&data.worker_status==='complete'&&sample&&typeof sample.n==='number'&&sample.n>0){
      var measured=side('red','Red guesses on unseen groups','Tiny illustrative sample; not a privacy proof.',
        (sample.correct/sample.n*100).toFixed(1)+'%','Unseen n='+sample.n+' · train n='+sample.train_n,
        'MEASURED NOW · tiny sample','waiting','guess');
      measured.visual.progress=sample.correct/sample.n;
      var live=frame('leakage','Fresh A/B smoke test','Can Red distinguish A from B?',
        'LATEST OPERATOR RUN · '+new Date(job.finished_at*1000).toLocaleTimeString()+' · bucket_hard · mock model',measured,3);
      live.headings=['No fresh raw baseline','Fresh bucket_hard smoke test'];
      live.scope=['Raw arm not run in this smoke test','4 train + 4 unseen groups; separate from saved matrix'];
      out.push(live);
      var controlFrames=measuredControls(data);
      if(controlFrames.length)out=out.filter(f=>!['vault','feedback','audit'].includes(f.case)).concat(controlFrames);
      return out; // Do not play historical matrix cells as results of this fresh job.
    }
    ['ordinary','boundary','overflow'].forEach(function(cohort,i){
      function result(policy){
        var r=((data.matrix||{}).rows||[]).find(x=>x.cohort===cohort&&x.policy===policy&&x.status==='SAVED');
        if(!r||typeof r.accuracy!=='number')return missing();
        var value=(r.accuracy*100).toFixed(1)+'%';
        var a=side('red','Red guesses the secret',policy==='raw'?'Actual release time':'Original 3/6/9s buckets',value,
          'Unseen-run accuracy · n='+r.n,r.accuracy>=.6?'DISTINGUISHABLE':'UNCERTAIN',r.accuracy>=.6?'bad':'waiting','guess');
        a.visual.progress=r.accuracy;a.facts={blue:'Secret A vs secret B',model:'Separate training and test runs',red:value+' correct guesses'};return a;
      }
      out.push({case:'leakage',phase:i,chapter:'Secret A/B evaluation',question:cohort==='ordinary'?'Ordinary traffic':cohort==='boundary'?'Probe a bucket boundary':'Force overflow',
        source:'Saved live gateway evaluation · mock model · local run',before:result('raw'),after:result('bucket'),
        labels:['Private worlds','Evaluation','Attacker result']});
    });
    var m=data.matrix||{};
    var a=side('none','Evaluation is incomplete','Missing policy arms have no measured result.',(m.saved||0)+'/'+(m.total||16),
      'Matrix cells saved','REMAINING ARMS: NOT RUN','waiting','guess');
    out.push(frame('leakage','Secret A/B evaluation','What has actually been measured?','Saved matrix coverage',a,3));
    var measured=measuredControls(data);
    if(measured.length)out=out.filter(f=>!['vault','feedback','audit'].includes(f.case)).concat(measured);
    return out;
  }
  function renderVisual(target,s){
    target.replaceChildren();var v=s.visual||{type:'output',value:s.facts.red,detail:s.result,state:s.tone};
    var graphic=document.createElement('div');graphic.className='scene-graphic graphic-'+v.type+' '+(v.state||'');
    function part(cls,text){var n=document.createElement('span');n.className=cls;n.textContent=text;graphic.append(n);return n;}
    if(v.type==='audit'){part('chain-node','01');part('chain-link','—');part('chain-node',v.verifier==='INVALID'?'×':'02');part('chain-link','—');part('chain-node','03');part('graphic-lock',v.state==='good'?'✓':'?');}
    else if(v.type==='network'){part('packet-node','RED');part('packet-arrow','→');part('boundary-wall',v.state==='good'?'⛨':'?');part('packet-node','PRIVATE');}
    else if(v.type==='vault'||v.type==='identity'){part('document-icon','▤');part('packet-arrow','→');part('graphic-lock',v.value==='SEALED'?'⛨':v.type==='identity'?'ID':'?');part('cipher-lines','••••\n••••');}
    else if(v.type==='feedback'){part('report-sheet','RANGE');part('budget-token','1');part('budget-token',v.value==='WITHHELD'?'×':'2');}
    else if(v.type==='latency'||v.type==='guess'){var track=part('meter-track','');var fill=document.createElement('span');fill.className='meter-fill';fill.style.width=(Math.max(0,Math.min(1,v.progress||0))*100)+'%';track.append(fill);}
    else part('speech-icon',v.type==='missing'?'?':'“ ”');
    target.append(graphic);var value=document.createElement('strong');value.className='visual-value';value.textContent=v.value||'Step pending';target.append(value);
    var detail=document.createElement('span');detail.className='visual-detail';detail.textContent=v.detail||'';target.append(detail);
  }
  return {options:options,coverage:coverage,additional:additional,renderVisual:renderVisual,
    group:function(f){return ['blocked','allowed','repeat','overflow','timing_real'].includes(f.case)?'timing':f.case;}};
})();
