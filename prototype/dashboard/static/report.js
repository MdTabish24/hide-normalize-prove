/* Complete evidence tables for the trusted operator. No evaluation is launched. */
window.storyReport=(function(){
  var $=function(id){return document.getElementById(id);};
  function fmt(x,d){return typeof x==='number'&&Number.isFinite(x)?x.toFixed(d===undefined?1:d):'NOT RUN';}
  function pct(x){return typeof x==='number'?fmt(x*100)+'%':'NOT RUN';}
  function tone(s){
    if(s==='FAIL'||s==='INVALID'||String(s).includes('leaked')||s==='LEAKED')return 'bad';
    if(['PASS','VALID','BLOCKED'].includes(s))return 'good';
    return 'waiting';
  }
  function cell(main,detail,color){return {main:String(main),detail:detail||'',color:color||''};}
  function table(id,rows){
    var fragment=document.createDocumentFragment();
    rows.forEach(function(row){
      var tr=document.createElement('tr');
      row.forEach(function(value,i){
        var v=typeof value==='object'?value:cell(value);
        var td=document.createElement(i===0?'th':'td');
        if(i===0)td.scope='row';
        var label=document.createElement('span');label.textContent=v.main;
        if(v.color)label.className='result-pill '+v.color;
        td.append(label);
        if(v.detail){var small=document.createElement('small');small.textContent=v.detail;td.append(small);}
        tr.append(td);
      });fragment.append(tr);
    });$(id).replaceChildren(fragment);
  }
  var cohorts=[['ordinary','Roz ke prompts','Normal traffic'],['boundary','Bucket ke kinare','Pehle bucket se just pehle / baad'],
    ['overflow','9s se zyada','Scaled overflow probes'],['deadline_near','Deadline ke paas','Compute cutoff ke aas-paas'],
    ['deadline_far','Deadline se door','Compute cutoff se door']];
  function matrixRows(data){
    var rows=data.matrix&&data.matrix.rows||[];
    return cohorts.map(function(c){
      return [cell(c[1],c[2])].concat(['raw','bucket','bucket_hard','window_hard'].map(function(policy){
        var r=rows.find(function(x){return x.cohort===c[0]&&x.policy===policy;});
        if(!r)return cell('—','Is matrix mein yeh arm nahi');
        if(r.status!=='SAVED'||typeof r.accuracy!=='number')return cell('NOT RUN','Result abhi saved nahi','waiting');
        var interval=Array.isArray(r.interval)&&r.interval.every(function(x){return typeof x==='number';})?
          ' · 95% CI '+r.interval.map(pct).join('–'):'';
        return cell(pct(r.accuracy),'test n='+r.n+interval+' · train '+pct(r.train_accuracy)+' · gap '+pct(r.gap),
          r.accuracy>=.6?'bad':'waiting');
      }));
    });
  }
  var explanations={
    'Test suite (host, Windows)':'Poore host suite ka saved result; selected checks neeche alag hain.',
    'Test suite (inside Docker image)':'Container mein code/tests chale.',
    'docker compose ps':'Saved snapshot mein services up thi; abhi ki health nahi.',
    'Isolation demo inside red-client':'Red private services, host aur internet tak pahunch saka ya nahi?',
    'Extra probes (audit/proxy from Red; egress of gateway, Blue, model)':'Audit/proxy access aur internet egress ka saved check.',
    'Audit verifier':'Finished run ki chain aur signed checkpoint verify hue.',
    'Audit tamper demo':'Log badalne ki 7 koshishein detect hui; individual cases neeche.',
    'Audit under matrix load (verifier on every run)':'Saved raw-policy runs ka audit; dusri policies ka certificate nahi.',
    'Timing matrix status':'Poora matrix abhi adhura hai; saved cells upar hain.',
    'Attack suite':'Alag attack-suite ka complete result abhi nahi.',
    'Feedback':'Noisy reports ke repeated-query analysis ka complete result nahi.',
    'Real-model latency vs 3/6/9 s buckets':'Real response times; padding offline lagayi gayi thi.',
    'Offline replay: window_hard W=3 s, D=2.4 s on the measured real latencies':'Real times par offline policy replay; live gateway test nahi.',
    'Real-model exact-canary scan of raw outputs':'Exact secret nahi mila; iska matlab poori secrecy nahi.',
    'Real-model rule disclosure in raw outputs (keyword scan + manual review)':'Canary ke bina bhi rule ka detail nikla.',
    'Same outputs behind score-only gateway':'Raw text rokne se 0 disclosures by design; feedback privacy prove nahi.',
    'External coding-agent red team':'raw / bucket_hard / window_hard: external agent sessions abhi NOT RUN.',
    'Dashboard backend tests':'Purana saved UI backend check; latest UI check ka poora suite nahi.',
    'Selected non-timing regression checks':'Selected checks hi; full suite nahi.',
    'Collector timing check (isolated host run)':'FAIL unresolved: slow collector se median gap 10 ms limit se bada tha.',
    'Dashboard Compose config validation':'Compose configuration valid; runtime isolation ka proof nahi.',
    'Dashboard Docker runtime / isolation':'Is dashboard version ki Docker isolation abhi verify nahi hui.',
    'Story/dashboard Python tests':'Current report projection, HTTP allowlisting aur existing UI regressions.',
    'Playback/report JavaScript tests':'Current animation decisions, all timing arms aur missing/failure handling.'
  };
  function evidenceRows(data){
    return (data.evidence||[]).filter(function(r){return !r.test.startsWith('Timing A-vs-B:');}).map(function(r){
      var scope=r.test.startsWith('Real-model')||r.test.startsWith('Same outputs')||r.test.startsWith('Offline replay:')?
        'Real model run, small sample · offline analysis':'Historical saved local check';
      if(r.test==='Story/dashboard Python tests'||r.test==='Playback/report JavaScript tests')scope='Latest saved UI/report check';
      return [cell(r.test,explanations[r.test]||'Saved evidence; fresh run nahi.'),
        cell(r.status,'',tone(r.status)),cell(r.metric||'No numeric summary saved',
        (r.policy==='—'?'':'Policy: '+r.policy+' · ')+'audit: '+r.audit_mode),scope];
    });
  }
  function caseRows(data){
    return (data.individual_checks||[]).map(function(r){return [cell(r.test,r.group),
      r.expected,cell(r.observed,r.observed==='NOT RUN'?'Saved case output missing':'Historical Docker log'),
      cell(r.status,r.group==='Audit tamper'&&r.expected==='INVALID'?'Tamper detect hona PASS hai':'',tone(r.status))];});
  }
  function storyRows(data){
    var rows=[];
    (data.requests||[]).forEach(function(r){
      rows.push([cell('Request #'+r.index,r.probe+' · '+r.rule),
        r.blue,cell(r.status+' / '+r.body_length+' bytes / '+r.response,'Release: '+fmt(r.total,3)+' s'),
        cell(r.output_contained===true?'PASS':r.output_contained===false?'FAIL':'NOT RUN','Exact output envelope only',
          r.output_contained===true?'good':r.output_contained===false?'bad':'waiting')]);
    });
    (data.runs||[]).forEach(function(r){
      var report=r.report||{},audit=r.audit||{};
      rows.push([cell('Run #'+r.index+' · final report','Evaluator count Red ko nahi diya gaya'),
        Array.isArray(report.safe_range)?report.safe_range.join(' – ')+' safe':'NOT RUN',
        'Repeat: '+(report.repeat_equal===true?'same range':report.repeat_equal===false?'CHANGED':'NOT RUN'),
        cell(report.repeat_equal===true?'PASS':report.repeat_equal===false?'FAIL':'NOT RUN','Range stability only',report.repeat_equal===true?'good':report.repeat_equal===false?'bad':'waiting')]);
      rows.push([cell('Run #'+r.index+' · third report','Per-identity read budget'),
        report.third_pending===true?'Pending; report withheld':report.third_pending===false?'Not pending':'NOT RUN',
        'Budget left: '+(typeof report.budget_left==='number'?report.budget_left+'/2':'NOT RUN'),
        cell(report.third_pending===true?'PASS':report.third_pending===false?'FAIL':'NOT RUN','Not a full adaptive-query privacy proof',report.third_pending===true?'good':report.third_pending===false?'bad':'waiting')]);
      rows.push([cell('Run #'+r.index+' · audit','Matched run verification'),audit.status||'NOT RUN',
        (typeof audit.count==='number'?audit.count:'NOT RUN')+' events',cell(audit.status||'NOT RUN','',tone(audit.status))]);
    });
    if(!rows.length)rows.push(['Recorded request','NOT RUN','NOT RUN',cell('NOT RUN','','waiting')]);
    return rows;
  }
  function realRows(data){
    var r=data.real_model||{},m=r.metrics||{},l=r.leaks||{},n=typeof r.attempts==='number'?r.attempts:'?';
    function count(x){return typeof x==='number'?x+'/'+n:'NOT RUN';}
    return [
      [cell('Exact secret canary','Exact-string scan'),count(l.raw_output_leaks),count(l.score_verdict_gateway_leaks),'0 exact hits broader secrecy prove nahi karte.'],
      [cell('Blue ka filter rule','Keyword scan + manual review'),count(l.raw_rule_leaks),count(l.score_verdict_gateway_rule_leaks),'Score-only: 0 by design; raw text Red tak nahi jaata.'],
      [cell('Response latency','Measured real API time; n='+(r.n||'NOT RUN')),
        'p50 / p95 / p99: '+fmt(m.p50_seconds,2)+' / '+fmt(m.p95_seconds,2)+' / '+fmt(m.p99_seconds,2)+' s',
        'Mean padding: +'+fmt(m.mean_added_latency_seconds,2)+' s','Offline bucket replay; no paired A/B secret labels.'],
      ['Slow responses','>3s: '+pct(m.overrun_rate_past_3s),'>9s: '+(typeof m.overflow_count_past_9s==='number'?m.overflow_count_past_9s:'NOT RUN'),'Overrun is a residual timing channel.']
    ];
  }
  return {matrixRows:matrixRows,evidenceRows:evidenceRows,caseRows:caseRows,storyRows:storyRows,realRows:realRows,
    render:function(data){
      $('matrix-summary').textContent=(data.matrix?data.matrix.saved+'/'+data.matrix.total:'0/16')+
        ' timing cells saved · missing results NOT RUN · fresh evaluation start nahi hui';
      $('real-scope').textContent='Real model run ('+((data.real_model||{}).provider||'NOT RUN')+
        '), small sample · same saved outputs, offline gateway comparison.';
      table('timing-results',matrixRows(data));table('real-results',realRows(data));
      table('check-results',evidenceRows(data));table('case-results',caseRows(data));table('story-results',storyRows(data));
    }};
})();
