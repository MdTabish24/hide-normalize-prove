// Every number below comes from a saved file in prototype/ (see "Source"). Nothing is rounded in our favour.
const A = [
{doors:["b-red","b-blue","b-model","b-audit"], title:"Open a direct door", attack:"Red tries to connect straight to Blue's filter, the model or the audit book, skipping the guard.",
 without:"Test on a deliberately weak setup (Red also attached to every service network): only 4 of 10 targets stayed blocked. Red could reach Blue's filter, the model and the audit book directly, by name and by address.",
 fix:"Red sits alone on its own network and can only reach the gateway. Blue, the model and the audit each have a private network with no internet.",
 other:[["Look up other services by name","No outside DNS inside Red's container."],["Use a port on the host","Ports are published on 127.0.0.1 only."],["Use the Docker control socket","It is not mounted."]],
 badge:"STOPPED", result:"10 of 10 direct targets were blocked from inside Red's container. Hardening check: 5 of 5 containers pass, 4 of 4 networks are internal (real Docker run).", src:"attack_suite_results.json (attack 1); eval/output/hardening/results.json"},
{doors:["b-red","b-disk","b-blue"], title:"Read files and secrets", attack:"Red looks for Blue's rule, passwords or the Docker socket on disk.",
 without:"Test on a deliberately weak setup (secrets given to Red's container, data volume mounted): the same test found Blue's token, the gateway key and Blue's sealed rule file.",
 fix:"Containers are read-only, run as a normal user, have no secrets in Red's environment, and Blue's rule is stored encrypted inside the gateway.",
 other:[["Environment variables","None found."],["Mounted folders","None found."],["Start new processes","Process and memory limits are set."]],
 badge:"STOPPED", result:"No Docker socket, Blue's config file not visible, no secret variables, no mounts. Hardening check passed (all 5 containers).", src:"attack_suite_results.json (attack 2); eval/output/hardening/results.json"},
{doors:["b-red","b-gateway"], title:"Pretend to be someone else", attack:"Red pretends to be Blue or the evaluator (10 tricks: wrong token, missing token, token inside the request...).",
 without:"Not measured. We did not build a weak gateway that ignores roles, so this test has no proof yet that it would catch a leak.",
 fix:"Only three role tokens exist, every endpoint checks the role, and Red always gets the same 202 'pending' reply.",
 other:[["Guess an admin URL","Same generic reply."],["Finish or change a run it does not own","Refused, same reply."]],
 badge:"STOPPED", result:"All 10 cases had no effect: Blue's rule unchanged, runs not finished by Red, every reply generic.", src:"attack_suite_results.json (attack 3)"},
{doors:["b-red","b-gateway"], title:"Send broken requests", attack:"Red sends 12 kinds of broken or forbidden requests and watches if the reply, or the time it takes, is different.",
 without:"With our older default policy (buckets) Red saw three different reply times, so it could tell its own bad requests from processed ones.",
 fix:"One fixed window. Every kind of request, even an error, gets the same 64-byte reply at the same time.",
 other:[["Too many requests at once (error 429)","Turned into the same reply."],["Huge request body","Same reply."],["Gateway crashes inside","Same reply."]],
 badge:"STOPPED", result:"Across all 12 cases: 1 reply shape and 1 release time. (The old default policy is bounded-leak.)", src:"attack_suite_results.json (attack 4)"},
{doors:["b-red","b-gateway","b-blue","b-model"], title:"Watch the clock", attack:"Red measures how long the reply takes, to guess whether Blue blocked the prompt (rule A) or allowed it (rule B).",
 without:"With no timing protection Red guesses right 98 to 100 percent of the time (mock) and 100 percent with the real model.",
 fix:"A fixed window: every reply comes at the same moment. Slow work keeps running in the background instead of being cancelled early.",
 other:[["Long answers from the model","Work continues, the reply still comes at the window."],["Many requests at once (flood)","Per-user limit; audit and database work moved off the main loop."],["Bucket edges (3, 6, 9 seconds)","No buckets any more, just one window."]],
 badge:"REDUCED", result:"Real model, normal prompts in four runs: 33.3%, 43.3%, 41.7% and 46.7%. Long answers 57.5%, flood 58.3%. The upper ends of the long and flood cases are above 60%, so we call it bounded, NOT proven safe.", src:"REAL_MODEL_REPORT.md; FINAL_REPORT.md"},
{doors:["b-red","b-model"], title:"Use the model's memory", attack:"A prompt the model has seen before is answered faster. Red uses that to learn what Blue let through.",
 without:"With a shared cache Red guesses right 95% of the time.",
 fix:"Every run gets its own cache area, and the fixed window hides speed differences.",
 other:[["The provider's own cache (DeepSeek)","We saw no speed-up on repeated prompts. That is only our own observation; we cannot see inside the provider."]],
 badge:"STOPPED", result:"45 to 48% with the separate cache (mock).", src:"attack_suite_results.json (attack 6)"},
{doors:["b-red","b-gateway"], title:"Read the final report", attack:"At the end Red gets a report of how many prompts Blue allowed. Red looks at extreme counts and averages many runs.",
 without:"If the report is exact at the edges, Red recognises 'none allowed' and 'all allowed' 100% of the time. Averaging 30 runs cuts the guessing error from 3.71 to 2.56.",
 fix:"The report is a noisy range, readable twice per run. The opt-in 'coarse' mode removes the fixed edges and gives the same answer for the same probes, so averaging does not help.",
 other:[["Read the report a third time","Generic 'pending' reply."]],
 badge:"REDUCED", result:"In simulation, exact recognition at the extremes drops from 100% to 24% (none allowed) and 47% (all allowed). Not tested with the real model and not closed.", src:"eval/output/coarse_report/results.json"},
{doors:["b-disk","b-blue","b-audit"], title:"Search logs and files", attack:"Red or Blue digs through logs, databases and audit files to find a prompt or the rule.",
 without:"Test with a deliberately careless Blue service that logs every prompt and the rule: the same scan found both the secret rule and the raw prompt in that log file.",
 fix:"Prompts are stored encrypted, the audit keeps only hashes, and Blue's service writes no logs and stores nothing. The opt-in BLUE_INLINE keeps the rule inside the gateway so Blue's code never even sees Red's prompt.",
 other:[["Gateway output","Scanned."],["Audit logs and checkpoints","Scanned."],["Docker volumes and container logs","Not scanned in our run."]],
 badge:"STOPPED", result:"18 files scanned: no plain trigger and no plain prompt found (only hashes).", src:"attack_suite_results.json (attack 8)"},
{doors:["b-red","b-gateway","b-audit"], title:"Flood the guard", attack:"Red sends a huge number of requests and watches how Blue's replies slow down.",
 without:"Blue's replies got slower: median +84 ms and the slowest 5% went from 911 ms to 1811 ms.",
 fix:"Database and audit work moved to worker threads, audit events sent in batches, and a fresh connection after any failed audit delivery (we found that one stuck connection froze the whole audit queue).",
 other:[["Audit queue fills up","Fixed: the queue peaked at 35 events instead of 10,000."],["Guard freezes for a moment","Work moved off the main loop."]],
 badge:"STOPPED", result:"After: median -0.0 ms, slowest 5% 909 to 910 ms, no shift found. One run, mock, local processes.", src:"eval/output/final_run (attack 9)"},
{doors:["b-red","b-gateway"], title:"Keep the computer busy", attack:"Red keeps every CPU core busy and watches whether replies arrive late.",
 without:"In one run 32 of 60 replies were more than 20 ms late under load (0 of 60 when idle).",
 fix:"The reply is released at the exact moment by a careful wait, plus the changes above.",
 other:[["Different machine","Not tested."]],
 badge:"REDUCED", result:"With our changes 3 of 3 runs showed no shift, but the no-changes control run also showed no shift this time. So we cannot say our change caused it. We do not count it as stopped.", src:"FINAL_REPORT.md (PARAMS v12)"},
{doors:["b-red","b-gateway"], title:"Flood from inside Docker", attack:"Same flood, but Red runs inside its own container and shares the computer with the guard.",
 without:"Without our changes: median +38 ms, slowest 5% from 915 ms to 2519 ms.",
 fix:"The same changes, plus an optional plan that gives Red and the gateway separate CPU cores (pin_cpus.py).",
 other:[["Small host with few cores","The plan scales down, or switches itself off below 4 cores."]],
 badge:"REDUCED", result:"The result changes from run to run: the same setup was 'leaking' once (912 to 1697 ms) and 'no shift' once (909 to 913 ms). We cannot call it closed.", src:"FINAL_REPORT.md (PARAMS v11 and v13)"}
];
// The other half of the job: a defence that hides everything is useless, Red must still learn something it can use.
const U={title:"Does Red still get useful feedback?",
 why:"Hiding the secret is only half of the job. Safety testing only works if Red can still find real weak spots in Blue's rule, so Red's attacks must stay strong.",
 default_:"What Red gets by default: one noisy range at the end of a run (how many of its prompts Blue allowed, as a range 12 wide), read at most twice. We have NOT measured how useful this is for finding a real bypass.",
 meter:[["No protection (exact feedback after every prompt)","A scripted attacker finds the planted bypass with a median of 7 probes (simulation). This is the best case for Red and the worst for the secret."],
  ["Our opt-in meter, no noise","The attacker finds the bypass in 100% of trials but needs a median of 60 probes (8 to 9 times more), and it can still tell rule A from B perfectly (100%)."],
  ["Our opt-in meter, 15% noise","Finds the bypass in 68.7% of trials within 150 probes, but still tells rule A from B 89% of the time."],
  ["Random guessing","About 1 in 12 (there are 12 candidate families)."]],
 honest:"So there is a real trade-off: more protection means weaker attacks, and our meter is not a fix for it. The planted-bypass test was run only for the opt-in meter, in simulation with a mock model. For the default report it was not run at all. A different design (exact feedback from a reference model that has no Blue rule) is an idea we did not build.",
 src:"FINAL_REPORT.md (problems P2 and P7); PARAMS.md (Evaluation 2); eval/meter_eval.py"};
const nav=document.getElementById("nav"), card=document.getElementById("card");
let i=0;
const esc=s=>s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function items(list){return "<ul>"+list.map(([d,s])=>`<li><b>${esc(d)}:</b> ${esc(s)}</li>`).join("")+"</ul>"}
function show(n){
  i=n;
  document.querySelectorAll(".box").forEach(b=>b.classList.remove("hl"));
  nav.querySelectorAll("button").forEach((b,k)=>b.classList.toggle("on",k===n));
  if(n<A.length){
    const a=A[n]; a.doors.forEach(d=>document.getElementById(d).classList.add("hl"));
    card.innerHTML=`<h2>Attack ${n+1} of ${A.length}: ${esc(a.title)}</h2><p>${esc(a.attack)}</p>
    <div class="blk bad"><h3>Without our solution</h3>${esc(a.without)}</div>
    <div class="blk fix"><h3>What our solution does</h3>${esc(a.fix)}</div>
    <div class="blk oth"><h3>Could it leak another way? What stops that?</h3>${items(a.other)}</div>
    <p><span class="badge ${a.badge}">${a.badge}</span> ${esc(a.result)}</p><p class="src">Source: ${esc(a.src)}</p>`;
  } else if(n===A.length){
    card.innerHTML=`<h2>${esc(U.title)}</h2><p>${esc(U.why)}</p>
    <div class="blk oth"><h3>What Red gets</h3>${esc(U.default_)}</div>
    <div class="blk fix"><h3>Strength of Red's attacks vs protection (planted-bypass test, simulation)</h3>${items(U.meter)}</div>
    <div class="blk bad"><h3>The honest part</h3>${esc(U.honest)}</div><p class="src">Source: ${esc(U.src)}</p>`;
  } else {
    const stopped=A.filter(a=>a.badge==="STOPPED").length, reduced=A.length-stopped;
    card.innerHTML=`<h2>Scoreboard</h2><div class="score"><div><b>${stopped}</b>stopped</div><div><b>${reduced}</b>reduced, not closed</div><div><b>1</b>out of scope</div></div>
    <div class="blk fix"><h3>What we can say</h3>Of 11 tested attack groups, ${stopped} were stopped and ${reduced} were reduced but not closed. These are single runs on one laptop, mostly with a mock model.</div>
    <div class="blk bad"><h3>What is still open</h3><ul><li>Timing with long answers and floods is bounded (about 58% with the real model), not proven safe.</li><li>Report extremes: reduced in simulation only.</li><li>Red's feedback: how useful the default report is for finding a real bypass was not measured (see the Feedback card).</li><li>CPU-load slip and Docker flood: the measurements are not stable, so we do not call them closed.</li></ul></div>
    <div class="blk oth"><h3>Out of scope (not tested, stated as risk)</h3>Kernel or container-runtime escape, hardware and shared-GPU side channels, and a compromised gateway. What we did check: the Red container is not privileged, has no capabilities, a read-only disk, no Docker socket and CPU, memory and process limits (5 of 5 containers).</div>
    <p class="src">Sources: FINAL_REPORT.md, REAL_MODEL_REPORT.md, PARAMS.md (test settings written before each run).</p>`;
  }
}
const LAST=A.length+1;
A.concat([{badge:"UTIL"},{badge:"END"}]).forEach((a,k)=>{const b=document.createElement("button");b.textContent=k<A.length?String(k+1):(k===A.length?"Feedback":"Score");if(k<A.length)b.className=a.badge==="STOPPED"?"s":"r";b.onclick=()=>show(k);nav.appendChild(b)});
document.getElementById("prev").onclick=()=>show(Math.max(0,i-1));
document.getElementById("next").onclick=()=>show(Math.min(LAST,i+1));
document.addEventListener("keydown",e=>{if(e.key==="ArrowRight")show(Math.min(LAST,i+1));if(e.key==="ArrowLeft")show(Math.max(0,i-1))});
show(0);
