// One attack at a time, two panels (without / with our solution), one Run button. All animation is SMIL, so Run = rewind + unpause.
// Every number is from a saved file in prototype/ (see "Source" under each attack). Nothing is rounded in our favour.
const at=b=>b==null?"":`<set attributeName="opacity" to="1" begin="${b}s" fill="freeze"/>`;
const op=b=>b==null?"":' opacity="0"';
const TX=(x,y,size,txt,cls,b,anchor,weight)=>`<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight||400}" text-anchor="${anchor||"start"}" class="${cls}"${op(b)}>${txt}${at(b)}</text>`;
const BX=(x,y,w,h,label,sub,stroke)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="9" class="fc ${stroke}" stroke-width="2.5"/>`+TX(x+w/2,y+h/2+(sub?-1:5),sub?14:13,label,"t",null,"middle",700)+(sub?TX(x+w/2,y+h/2+16,10.5,sub,"m",null,"middle"):"");
const GROW=(x,y,w,h,cls,b,d)=>`<rect x="${x}" y="${y}" width="0" height="${h}" rx="4" class="${cls}"><animate attributeName="width" from="0" to="${w}" begin="${b}s" dur="${d}s" fill="freeze"/></rect>`;
const ARROW=(x1,y1,x2,y2,cls,b,d)=>`<line x1="${x1}" y1="${y1}" x2="${x1}" y2="${y1}" stroke-width="3" stroke-linecap="round" class="${cls}"><animate attributeName="x2" from="${x1}" to="${x2}" begin="${b}s" dur="${d}s" fill="freeze"/><animate attributeName="y2" from="${y1}" to="${y2}" begin="${b}s" dur="${d}s" fill="freeze"/></line>`;
const DOT=(x1,y1,x2,y2,cls,b,d)=>`<circle r="7" cx="${x1}" cy="${y1}" class="${cls}" opacity="0"><set attributeName="opacity" to="1" begin="${b}s" end="${b+d}s"/><animate attributeName="cx" from="${x1}" to="${x2}" begin="${b}s" dur="${d}s"/><animate attributeName="cy" from="${y1}" to="${y2}" begin="${b}s" dur="${d}s"/></circle>`;
const verdict=v=>v.lines.map((l,i)=>TX(210,(v.lines.length===1?234:222)+i*17,12.5,l,v.cls,3.4+i*0.2,"middle",700)).join("");
const wrap=inner=>`<svg viewBox="0 0 420 250" role="img">${inner}</svg>`;

// ---- panel kinds ----
const KIND={
 reach:p=>{const n=p.targets.length,gap=200/n;let s=BX(8,85,84,60,"Red","attacker","sr");
   if(p.wall)s+=`<rect x="196" y="8" width="10" height="176" class="fg"/>`+TX(201,198,11,"guard","cg",null,"middle");
   p.targets.forEach((t,i)=>{const ty=8+i*gap+(gap-42)/2,cy=ty+21,b=0.2+i*0.4,ex=p.wall?190:296;
     s+=BX(300,ty,112,42,t,"","sb")+ARROW(92,115,ex,cy,"sr",b,0.6)+(p.wall?TX(ex+6,cy+6,18,"X","cr",b+0.6,"middle",700):TX(356,ty-2,10.5,"REACHED","cr",b+0.6,"middle",700))});
   return s},
 found:p=>{let s=`<rect x="8" y="8" width="404" height="190" rx="10" class="fc sl" stroke-width="2"/>`+TX(20,30,12,p.header,"m",null,"start",700);
   p.items.forEach((it,i)=>{const y=70+i*40,b=0.3+i*0.5;s+=TX(20,y,13,it,"t",null)+TX(400,y,13,p.found?"FOUND":"not found",p.found?"cr":"cg",b,"end",700)});return s},
 tricks:p=>{let s="";p.items.forEach((it,i)=>{const x=6+(i%2)*208,y=22+Math.floor(i/2)*36,b=0.15+i*0.22;
   s+=`<rect x="${x}" y="${y}" width="200" height="28" rx="6" class="fc sl" stroke-width="1.5"/>`+TX(x+8,y+18,11,it,"t",null)+TX(x+194,y+18,10.5,"same reply","cg",b,"end",700)});return s},
 times:p=>{const W=200,x0=140,step=p.rows.length>3?40:54;let s=p.head?TX(8,16,11,p.head,"m",null,"start"):"";
   p.rows.forEach((r,i)=>{const y=30+i*step,b=0.3+i*0.5,w=Math.max(3,W*r.val/p.max),c=r.cls==="fr"?"cr":r.cls==="fa"?"ca":"cg";
     s+=TX(8,y+16,12,r.label,"m",null)+GROW(x0,y,w,24,r.cls||"fg",b,1.1)+TX(x0+w+6,y+17,12,r.text,c,b+1.1,"start",700)});
   if(p.line){const lx=x0+W*p.line.v/p.max;s+=`<line x1="${lx}" y1="22" x2="${lx}" y2="190" stroke-width="2" stroke-dasharray="5 4" class="sm"/>`+TX(lx,202,10.5,p.line.label,"m",null,"middle")}return s},
 note:p=>p.lines.map((l,i)=>TX(210,70+i*26,13,l,"m",null,"middle")).join(""),
 doors:p=>{const names=["Network","Timing","Errors","Cache","Load","Logs"];let s=BX(8,75,84,60,"Red","attacker","sr")+BX(318,75,94,60,"Secret rule","in Blue's filter","sb");
   names.forEach((n,i)=>{const y=14+i*34,b=0.2+i*0.4;s+=ARROW(92,105,314,y+8,"sr",b,0.6)+TX(204,y+2,11,n,"cr",b+0.2,"middle",700)});
   return s+TX(365,172,34,"?","ca",3,"middle",700)},
 design:p=>BX(6,85,78,56,"Red","locked in","sr")+BX(150,85,104,56,"Gateway","the guard","sg")+BX(318,6,96,50,"Blue filter","private","sb")+BX(318,76,96,50,"Client LLM","own cache","sb")+BX(318,146,96,50,"Audit book","signed","sb")+
   `<line x1="84" y1="113" x2="150" y2="113" stroke-width="3" class="sg"/><line x1="254" y1="105" x2="318" y2="31" stroke-width="3" class="sb"/><line x1="254" y1="113" x2="318" y2="101" stroke-width="3" class="sb"/><line x1="254" y1="121" x2="318" y2="171" stroke-width="3" class="sb"/>`+
   DOT(84,113,150,113,"fr",0.2,0.6)+DOT(254,105,318,31,"fb",0.9,0.7)+DOT(254,113,318,101,"fb",1.2,0.7)+DOT(254,121,318,171,"fb",1.5,0.7)+DOT(150,113,84,113,"fg",2.4,0.7)+TX(117,78,11,"same reply","cg",2.4,"middle",700),
 score:p=>{const G=["1 Network","2 Files","3 Fake tokens","4 Error messages","6 Model cache","8 Log search","9 Flood (local)"],A=["5 Timing (real 58%)","7 Final report","10 CPU-load slip","11 Docker flood"];let s="",k=0;
   const tile=(n,x,y,c,b)=>`<g opacity="0">${at(b)}<rect x="${x}" y="${y}" width="200" height="26" rx="6" class="${c}"/><text x="${x+100}" y="${y+18}" font-size="12" font-weight="700" fill="#fff" text-anchor="middle">${n}</text></g>`;
   G.forEach((n,i)=>s+=tile(n,6+(i%2)*208,6+Math.floor(i/2)*30,"fg",0.2+i*0.25));
   A.forEach((n,i)=>s+=tile(n,6+(i%2)*208,6+4*30+Math.floor(i/2)*30,"fa",2.2+i*0.25));
   return s+`<g opacity="0">${at(3.4)}<rect x="6" y="${6+6*30}" width="408" height="26" rx="6" class="fk"/><text x="210" y="${6+6*30+18}" font-size="12" font-weight="700" fill="#fff" text-anchor="middle">Out of scope: kernel, hardware/GPU, compromised gateway</text></g>`}
};
const P=(h,kind,data,v)=>({h,kind,data,v});
const V=(cls,...lines)=>({cls,lines});

const A=[
{nav:"Overview",cls:"o",title:"The problem and our design",attack:"Red wants to learn Blue's secret rule from anything it can see. We close the doors one by one.",
 L:P("The problem","doors",{},V("cr","Red needs only ONE open door:","network, timing, errors, cache, load or logs.")),
 R:P("Our design","design",{},V("cg","Red only reaches the guard: same short reply,","same time, for everyone (real run: 3.0 s).")),
 fix:"Everything runs in Docker with separate private networks. Blue's filter is private, the model's cache is separate for every run, and every event goes into a signed audit book that detects any edit.",badge:"INFO",result:"Eleven attacks follow. Use the buttons above.",src:"prototype/README.md"},
{nav:"1 Network",cls:"s",title:"Attack 1: open a direct door",attack:"Red tries to connect straight to Blue's filter, the model or the audit book, skipping the guard.",
 L:P("Without our solution (weak setup)","reach",{targets:["Blue filter","Model","Audit book"],wall:false},V("cr","Weak setup: only 4 of 10 targets blocked.","Red reaches Blue, the model and the audit.")),
 R:P("With our solution","reach",{targets:["Blue filter","Model","Audit book"],wall:true},V("cg","10 of 10 targets blocked.","Hardening: 4 of 4 networks internal.")),
 fix:"Red sits alone on its own network and can only reach the gateway. Blue, the model and the audit each have a private network with no internet. No outside DNS inside Red's container, ports only on 127.0.0.1, no Docker socket.",
 badge:"STOPPED",result:"10 of 10 direct targets blocked from inside Red's container (real Docker run). The weak setup (Red attached to every network) leaked: 6 of 10 reachable.",src:"attack_suite_results.json (attack 1); eval/output/weak_controls/results.json; eval/output/hardening/results.json"},
{nav:"2 Files",cls:"s",title:"Attack 2: read files and secrets",attack:"Red looks in its own container for Blue's rule, passwords or the Docker socket.",
 L:P("Without our solution (weak setup)","found",{header:"What Red finds in its own container",items:["BLUE_TOKEN in Red's environment","GATEWAY_KEY in Red's environment","Blue's sealed rule file (volume mounted)"],found:true},V("cr","Weak setup: secrets and the rule file found.")),
 R:P("With our solution","found",{header:"What Red finds in its own container",items:["Secret variables","Docker socket","Blue's rule file"],found:false},V("cg","Nothing found: read-only disk, no secrets,","no mounts. Hardening: 5 of 5 containers pass.")),
 fix:"Containers are read-only, run as a normal user, have no secrets in Red's environment, and Blue's rule is stored encrypted inside the gateway only.",
 badge:"STOPPED",result:"No Docker socket, Blue's config file not visible, no secret variables, no mounts.",src:"attack_suite_results.json (attack 2); eval/output/weak_controls/results.json"},
{nav:"3 Tokens",cls:"s",title:"Attack 3: pretend to be someone else",attack:"Red pretends to be Blue or the evaluator, with 10 tricks (wrong token, no token, role claimed in the request...).",
 L:P("Without our solution","note",{lines:["Not measured.","We did not build a weak gateway that ignores","roles, so this test has no proof yet","that it would catch a leak."]},V("cr","No baseline.")),
 R:P("With our solution","tricks",{items:["Red sets Blue's rule","Red finishes a run","Red reads evaluator report","Blue submits as Red","Evaluator submits as Red","Role claim in the request","No token","Token without Bearer","Path trick in run id","Report before finish"]},V("cg","10 of 10 tricks: no effect,","every reply is the same 202.")),
 fix:"Only three role tokens exist, every endpoint checks the role, and Red always gets the same 202 'pending' reply, so a refused trick looks like an accepted one.",
 badge:"STOPPED",result:"All 10 cases had no effect. Caveat: this test has no positive control (no weak gateway was built).",src:"attack_suite_results.json (attack 3)"},
{nav:"4 Errors",cls:"s",title:"Attack 4: send broken requests",attack:"Red sends 12 kinds of broken or forbidden requests and watches if the reply, or the time it takes, differs.",
 L:P("Without our solution (old policy)","times",{head:"Reply time (mock time units)",max:1,rows:[{label:"Fast request",val:0.3,text:"0.3 s",cls:"fr"},{label:"Slower request",val:0.6,text:"0.6 s",cls:"fr"},{label:"Error request",val:0.9,text:"0.9 s",cls:"fr"}]},V("cr","Old policy: 3 different reply times.","Red can tell its own bad requests apart.")),
 R:P("With our solution","times",{head:"Reply time (mock time units)",max:1,rows:[{label:"Fast request",val:0.9,text:"0.9 s",cls:"fg"},{label:"Slower request",val:0.9,text:"0.9 s",cls:"fg"},{label:"Error request",val:0.9,text:"0.9 s",cls:"fg"}]},V("cg","All 12 kinds: 1 reply shape,","1 reply time.")),
 fix:"One fixed window: every kind of request, even an error, gets the same 64-byte reply at the same moment. Too many requests, huge bodies and internal crashes are turned into the same reply.",
 badge:"STOPPED",result:"Across all 12 cases: 1 reply shape and 1 release time. (The old default policy is a bounded leak.)",src:"attack_suite_results.json (attack 4)"},
{nav:"5 Timing",cls:"r",title:"Attack 5: watch the clock",attack:"Red measures how long the reply takes to guess whether Blue blocked the prompt (rule A) or allowed it (rule B).",
 L:P("Without our solution","times",{head:"Reply time, real model",max:3.2,rows:[{label:"Rule A: blocked",val:0.07,text:"0.07 s",cls:"fr"},{label:"Rule B: allowed",val:1.0,text:"1.0 s",cls:"fr"}]},V("cr","No protection: Red guesses the secret","98-100% of the time (real model: 100%).")),
 R:P("With our solution","times",{head:"Reply time, real model",max:3.2,line:{v:3.0,label:"fixed reply time"},rows:[{label:"Rule A: blocked",val:3.0,text:"3.0 s",cls:"fg"},{label:"Rule B: allowed",val:3.0,text:"3.0 s",cls:"fg"}]},V("ca","Normal prompts: Red gets 33-47% in 4 runs (50% = guessing).","Long answers 57.5%, flood 58.3%: bounded, not safe.")),
 fix:"A fixed window: every reply comes at the same moment. Slow work keeps running in the background instead of being cancelled early, and there is a per-user limit on requests in flight.",
 badge:"REDUCED",result:"Real model, normal prompts in four runs: 33.3%, 43.3%, 41.7% and 46.7%. Long answers 57.5%, flood 58.3%. The upper ends of the long and flood cases are above 60%, so it is bounded, NOT proven safe.",src:"REAL_MODEL_REPORT.md; FINAL_REPORT.md"},
{nav:"6 Cache",cls:"s",title:"Attack 6: use the model's memory",attack:"A prompt the model has seen before is answered faster. Red uses that to learn what Blue let through.",
 L:P("Without our solution","times",{head:"Red's correct guesses",max:100,line:{v:50,label:"50% = guessing"},rows:[{label:"Shared cache",val:95,text:"95%",cls:"fr"}]},V("cr","Shared cache: a repeated prompt answers faster,","Red guesses right 95% of the time.")),
 R:P("With our solution","times",{head:"Red's correct guesses",max:100,line:{v:50,label:"50% = guessing"},rows:[{label:"Own cache per run",val:46,text:"45-48%",cls:"fg"}]},V("cg","Own cache area per run: 45-48% (mock).","The provider's own cache: no speed-up seen.")),
 fix:"Every run gets its own cache area, and the fixed window hides speed differences. For the provider's hosted cache we only have our own observation: no speed-up on repeated prompts.",
 badge:"STOPPED",result:"45 to 48% with the separate cache (mock).",src:"attack_suite_results.json (attack 6)"},
{nav:"7 Report",cls:"r",title:"Attack 7: read the final report",attack:"At the end Red gets a report of how many prompts Blue allowed. Red looks at the extreme counts.",
 L:P("Without our solution","times",{head:"Red recognises the exact count (simulation)",max:100,rows:[{label:"None allowed (0)",val:100,text:"100%",cls:"fr"},{label:"All allowed (16)",val:100,text:"100%",cls:"fr"}]},V("cr","Exact report edges: Red recognises the","extreme counts every time.")),
 R:P("With our solution (coarse mode)","times",{head:"Red recognises the exact count (simulation)",max:100,rows:[{label:"None allowed (0)",val:24,text:"24%",cls:"fa"},{label:"All allowed (16)",val:47,text:"47%",cls:"fa"}]},V("ca","Lower, but NOT closed. Not tested with","the real model; averaging also reduced.")),
 fix:"The report is a noisy range, readable twice per run. The opt-in 'coarse' mode removes the fixed edges and gives the same answer for the same probes, so averaging many runs does not help.",
 badge:"REDUCED",result:"In simulation, exact recognition at the extremes drops from 100% to 24% (none allowed) and 47% (all allowed). Not tested with the real model.",src:"eval/output/coarse_report/results.json"},
{nav:"8 Logs",cls:"s",title:"Attack 8: search logs and files",attack:"Red or Blue digs through logs, databases and audit files to find a prompt or the secret rule.",
 L:P("Without our solution (careless Blue)","found",{header:"What the scan finds",items:["Blue's log file: the secret rule","Blue's log file: Red's raw prompt"],found:true},V("cr","A Blue service that logs everything:","the same scan finds both.")),
 R:P("With our solution","found",{header:"What the scan finds (18 files)",items:["The secret rule","Red's raw prompt"],found:false},V("cg","Nothing found. Only hashes are stored.","(Docker volumes were not scanned.)")),
 fix:"Prompts are stored encrypted, the audit keeps only hashes, and Blue's service writes no logs and stores nothing. The opt-in BLUE_INLINE keeps the rule inside the gateway so Blue's code never even sees Red's prompt.",
 badge:"STOPPED",result:"18 files scanned: no plain trigger and no plain prompt (hashes only).",src:"attack_suite_results.json (attack 8); eval/output/weak_controls/results.json"},
{nav:"9 Flood",cls:"s",title:"Attack 9: flood the guard",attack:"Red sends a huge number of requests and watches how Blue's replies slow down.",
 L:P("Without our solution","times",{head:"Blue's slowest 5% of replies, local test",max:2000,rows:[{label:"Quiet",val:911,text:"911 ms",cls:"fg"},{label:"Red floods",val:1811,text:"1811 ms",cls:"fr"}]},V("cr","Blue's replies get slower under the flood:","median +84 ms.")),
 R:P("With our solution","times",{head:"Blue's slowest 5% of replies, local test",max:2000,rows:[{label:"Quiet",val:909,text:"909 ms",cls:"fg"},{label:"Red floods",val:910,text:"910 ms",cls:"fg"}]},V("cg","No shift found (one run, mock).","Audit queue: 10,000 waiting -> 35.")),
 fix:"Database and audit work moved to worker threads, audit events sent in batches, and a fresh connection after any failed audit delivery (we found one stuck connection froze the whole audit queue).",
 badge:"STOPPED",result:"After: median -0.0 ms, slowest 5% 909 to 910 ms, no shift found. One run, mock, local processes.",src:"eval/output/final_run (attack 9); FINAL_REPORT.md"},
{nav:"10 CPU",cls:"r",title:"Attack 10: keep the computer busy",attack:"Red keeps every CPU core busy and watches whether replies arrive late.",
 L:P("Without our solution","times",{head:"Replies more than 20 ms late (of 60), one earlier run",max:60,rows:[{label:"Computer idle",val:0.6,text:"0 of 60",cls:"fg"},{label:"Computer busy",val:32,text:"32 of 60",cls:"fr"}]},V("cr","Earlier run: 32 of 60 replies late under load,","0 of 60 when idle.")),
 R:P("With our solution","times",{head:"Replies more than 20 ms late (of 60), 3 runs",max:60,rows:[{label:"Computer idle",val:0.6,text:"0-2 of 60",cls:"fg"},{label:"Computer busy",val:0.6,text:"0-1 of 60",cls:"fg"}]},V("ca","No shift in 3 of 3 runs, BUT the control run","(no changes) also showed none: not proven.")),
 fix:"The reply is released at the exact moment by a careful wait, plus the changes of attack 9. We cannot say these changes caused the result, so we do not count it as stopped.",
 badge:"REDUCED",result:"With our changes 3 of 3 runs showed no shift, but the no-changes control run also showed none this time (46 of 60 idle against 41 of 60 busy).",src:"FINAL_REPORT.md (PARAMS v12)"},
{nav:"11 Docker",cls:"r",title:"Attack 11: flood from inside Docker",attack:"The same flood, but Red runs inside its own container and shares the computer with the guard.",
 L:P("Without our solution","times",{head:"Blue's slowest 5% of replies, Docker",max:2600,rows:[{label:"Quiet",val:915,text:"915 ms",cls:"fg"},{label:"Red floods",val:2519,text:"2519 ms",cls:"fr"}]},V("cr","Without our changes: median +38 ms,","slowest 5% 915 -> 2519 ms.")),
 R:P("With our solution","times",{head:"Blue's slowest 5% of replies, Docker",max:2600,rows:[{label:"Quiet",val:912,text:"912 ms",cls:"fg"},{label:"Red floods",val:1697,text:"1697 ms",cls:"fa"}]},V("ca","With our changes: 912 -> 1697 ms; another run","gave 909 -> 913. Varies: NOT closed.")),
 fix:"The same changes, plus an optional plan that gives Red and the gateway separate CPU cores (pin_cpus.py). It scales down to small hosts and switches itself off below 4 cores.",
 badge:"REDUCED",result:"The result changes from run to run: the same setup was 'leaking' once (912 to 1697 ms) and 'no shift' once (909 to 913 ms). We cannot call it closed.",src:"FINAL_REPORT.md (PARAMS v11 and v13)"},
{nav:"Feedback",cls:"o",title:"Does Red still get useful feedback?",attack:"Hiding the secret is only half of the job: Red must still find real weak spots in Blue's rule, so Red's attacks must stay strong.",
 L:P("No protection (exact feedback)","times",{head:"Probes needed to find the planted bypass",max:60,rows:[{label:"Probes",val:7,text:"7",cls:"fg"}]},V("cg","Best for Red, worst for the secret.","(simulation, mock model)")),
 R:P("Our opt-in meter","times",{head:"Probes needed to find the planted bypass",max:60,rows:[{label:"Probes",val:60,text:"60",cls:"fa"}]},V("ca","8-9x more probes; still tells rule A from B","(100%; 89% with noise). Default report: not measured.")),
 fix:"A real trade-off: more protection means weaker attacks, and our meter is not a fix for it. The planted-bypass test was run only for the opt-in meter, in simulation. For the default report it was not run at all.",
 badge:"INFO",result:"Meter without noise: finds the bypass in 100% of trials. With 15% noise: 68.7% within 150 probes. Random guessing: about 1 in 12.",src:"FINAL_REPORT.md (P2, P7); PARAMS.md (Evaluation 2); eval/meter_eval.py"},
{nav:"Score",cls:"o",title:"Scoreboard",attack:"Of 11 tested attack groups: 7 stopped, 4 reduced but not closed, plus 1 group out of scope.",single:true,
 L:P("11 attack groups","score",{},V("cg","7 stopped   |   4 reduced, not closed   |   1 out of scope")),
 fix:"These are single runs on one laptop, mostly with a mock model. Settings were written before each run and every result file is on GitHub. We never say 'secure'. Out of scope and not tested: kernel or runtime escape, hardware and GPU side channels, a compromised gateway (we only checked that Red's container has no special rights).",
 badge:"INFO",result:"Still open: timing with long answers and floods (about 58% with the real model), report extremes (simulation only), CPU-load slip and Docker flood (not stable), and how useful the default report is for Red.",src:"FINAL_REPORT.md; REAL_MODEL_REPORT.md; PARAMS.md"}
];

const $=id=>document.getElementById(id);
let cur=0;
const esc=s=>s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const panel=(p,css)=>`<div class="panel ${css}"><h3>${esc(p.h)}</h3>${wrap(KIND[p.kind](p.data)+verdict(p.v))}</div>`;
function svgs(){return [...document.querySelectorAll("#panels svg")]}
function rewind(){svgs().forEach(s=>{s.pauseAnimations();s.setCurrentTime(0)})}
function run(){svgs().forEach(s=>{s.setCurrentTime(0);s.unpauseAnimations()})}
function load(n){
  cur=Math.max(0,Math.min(A.length-1,n));const a=A[cur];
  document.querySelectorAll("#nav button").forEach((b,k)=>b.classList.toggle("on",k===cur));
  $("title").textContent=a.title;$("attack").textContent=a.attack;
  $("panels").className="panels"+(a.single?" one":"");
  $("panels").innerHTML=a.single?panel(a.L,"single"):panel(a.L,"no")+panel(a.R,"yes");
  $("fix").innerHTML=`<b>${a.single?"What we can say":"What our solution actually does"}</b>${esc(a.fix)}`;
  $("result").innerHTML=`<span class="badge ${a.badge}">${a.badge}</span> ${esc(a.result)}`;
  $("src").textContent="Source: "+a.src;
  rewind();
}
A.forEach((a,k)=>{const b=document.createElement("button");b.textContent=a.nav;b.className=a.cls;b.onclick=()=>load(k);$("nav").appendChild(b)});
$("run").onclick=run;$("next").onclick=()=>load(cur+1);$("back").onclick=()=>load(cur-1);
document.addEventListener("keydown",e=>{if(e.key==="ArrowRight")load(cur+1);else if(e.key==="ArrowLeft")load(cur-1);else if(e.key===" "||e.key==="Enter"){e.preventDefault();run()}});
load(0);
