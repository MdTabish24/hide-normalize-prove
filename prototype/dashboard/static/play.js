const NS="http://www.w3.org/2000/svg";
// ---- tiny SVG helpers (all animation is SMIL, so pause/resume = svg.pauseAnimations()/unpauseAnimations()) ----
const show=(b,e)=>`<set attributeName="opacity" to="1" begin="${b}s"${e?` end="${e}s"`:""} fill="${e?"remove":"freeze"}"/>`;
const T=(x,y,s,txt,cls,b,e,anchor="start",w="400")=>`<text x="${x}" y="${y}" font-size="${s}" font-weight="${w}" text-anchor="${anchor}" class="${cls}" opacity="0">${txt}${show(b,e)}</text>`;
const R=(x,y,w,h,fill,b,e,extra="")=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" class="${fill}" ${extra} opacity="0">${show(b,e)}</rect>`;
const BOX=(x,y,w,h,label,sub,col,b,e)=>`<g opacity="0">${show(b,e)}<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" class="fc ${col}" stroke-width="2.5"/><text x="${x+w/2}" y="${y+h/2-2}" text-anchor="middle" font-size="17" font-weight="700" class="t">${label}</text><text x="${x+w/2}" y="${y+h/2+18}" text-anchor="middle" font-size="12" class="m">${sub}</text></g>`;
const GROW=(x,y,w,h,fill,b,d)=>`<rect x="${x}" y="${y}" width="0" height="${h}" rx="5" class="${fill}"><animate attributeName="width" from="0" to="${w}" begin="${b}s" dur="${d}s" fill="freeze"/></rect>`;
const LINE=(x1,y1,x2,y2,cls,b,dash="")=>`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke-width="3" class="${cls}" ${dash?`stroke-dasharray="${dash}"`:""} opacity="0">${show(b)}</line>`;
const DOT=(x1,y1,x2,y2,cls,b,d,hide)=>`<circle r="8" class="${cls}" cx="${x1}" cy="${y1}" opacity="0"><set attributeName="opacity" to="1" begin="${b}s" end="${b+d}s"/><animate attributeName="cx" from="${x1}" to="${x2}" begin="${b}s" dur="${d}s" fill="${hide?"remove":"freeze"}"/><animate attributeName="cy" from="${y1}" to="${y2}" begin="${b}s" dur="${d}s" fill="${hide?"remove":"freeze"}"/></circle>`;
const svg=(inner)=>`<svg id="sv" viewBox="0 0 800 340" role="img">${inner}</svg>`;

// ---- the seven scenes: dur = seconds of the matching part of the talk ----
const SCENES=[
{name:"1 Intro",dur:25,cap:"Hi, we are Team Ctrl Alt. Our project is Hide, Normalize, Prove: how can a Red team, a Blue team and a client LLM share one sandbox without anyone leaking secrets?",
 draw:()=>svg(`<rect x="110" y="150" width="580" height="150" rx="16" fill="none" class="sm" stroke-width="2" stroke-dasharray="8 6" opacity="0">${show(6)}</rect>`+
   T(400,70,34,"Hide, Normalize, Prove","t",0.5,0,"middle","700")+T(400,108,18,"Team Ctrl Alt","m",2,0,"middle")+
   T(400,142,13,"one shared sandbox","m",6,0,"middle")+BOX(140,180,150,80,"Red team","attacks","sr",8)+BOX(325,180,150,80,"Blue team","private filter","sb",10)+BOX(510,180,150,80,"Client LLM","clean model","sg",12))},
{name:"2 Problem",dur:30,cap:"If Red can learn Blue's secret rule from anything it can see, the test is worthless. Not only the network: timing, errors, cache, load, even log files.",
 draw:()=>{const probes=["Network","Timing","Errors","Cache","Load","Logs"];let s=BOX(30,125,150,90,"Red team","tries everything","sr",0.3)+BOX(610,125,160,90,"Secret rule","inside Blue's filter","sb",0.6);
   probes.forEach((p,i)=>{const y=40+i*52,b=2+i*4;s+=LINE(185,170,605,y+10,"sr",b,"6 5")+T(395,y-4,14,p,"cr",b,0,"middle","700")+DOT(185,170,605,y+10,"fr",b,2.2,true)});
   return svg(s+T(690,238,64,"?","ca",26,0,"middle","700")+T(400,325,15,"Red only needs ONE open door.","t",24,0,"middle","700"))}},
{name:"3 What we built",dur:35,cap:"Red is locked in its own network and can only talk to the gateway. The guard gives the same short reply, at the same time, whatever happens inside.",
 draw:()=>svg(BOX(20,125,140,90,"Red team","locked in","sr",0.3)+BOX(300,125,170,90,"Gateway","the guard","sg",1)+BOX(620,25,160,70,"Blue filter","private","sb",1.6)+BOX(620,135,160,70,"Client LLM","own cache per run","sb",2)+BOX(620,245,160,70,"Audit book","signed","sb",2.4)+
   LINE(160,170,300,170,"sg",3)+LINE(470,150,620,60,"sb",3.5)+LINE(470,170,620,170,"sb",3.5)+LINE(470,190,620,280,"sb",3.5)+
   DOT(160,170,300,170,"fr",5,2.5,true)+DOT(470,160,620,60,"fb",8,2.5,true)+DOT(470,170,620,170,"fb",11,2.5,true)+DOT(470,180,620,280,"fb",14,2.5,true)+
   `<rect x="170" y="150" width="120" height="40" rx="8" class="fc sg" stroke-width="2" opacity="0">${show(21)}</rect>`+T(230,176,13,"same reply","cg",21,0,"middle","700")+DOT(300,170,160,170,"fg",21,3,false)+
   T(230,235,16,"always 64 bytes, always at 3.0 s","t",24,0,"middle","700")+T(230,258,13,"(real run: median 3.008 s)","m",24,0,"middle")+T(400,325,15,"Everything runs in Docker with separate private networks.","m",28,0,"middle"))},
{name:"4 Eleven attacks",dur:105,cap:"We built eleven attacks and measured each one. Four direct doors stopped. Timing, cache and flood shown below.",
 draw:()=>{let s="";
   // a) doors 0-22
   s+=T(400,30,20,"Doors: network, files, fake tokens, error messages","t",0.3,22,"middle","700")+BOX(20,110,130,80,"Red","","sr",0.5,22)+`<rect x="330" y="70" width="14" height="200" class="fg" opacity="0">${show(1,22)}</rect>`+T(337,288,13,"guard","cg",1,22,"middle")+BOX(640,110,140,80,"Services","Blue, model, audit","sb",0.5,22);
   [0,1,2,3].forEach(i=>{const y=95+i*35,b=3+i*2;s+=`<g opacity="0">${show(b,22)}<line x1="150" y1="${y}" x2="326" y2="${y}" stroke-width="3" class="sr"/><text x="337" y="${y+5}" font-size="18" class="cr" font-weight="700">X</text></g>`+T(240,y-6,12,["network","files","tokens","errors"][i],"m",b,22,"middle")});
   s+=T(400,306,16,"All four stopped.","cg",10,22,"middle","700")+T(400,328,13,"We also tested weak setups (Red on every network, secrets given, Blue logging): the leak was caught.","cg",13,22,"middle","400");
   // b) timing 22-62
   s+=T(400,30,20,"Timing: how long does the reply take?","t",22.3,62,"middle","700")+T(30,80,14,"Rule A: prompt blocked","m",22.5,62)+T(30,125,14,"Rule B: prompt allowed","m",22.5,62)+
      `<g opacity="0">${show(23,40)}<rect x="200" y="62" width="0" height="24" rx="4" class="fr"><animate attributeName="width" from="0" to="13" begin="24s" dur="1s" fill="freeze"/></rect><rect x="200" y="107" width="0" height="24" rx="4" class="fr"><animate attributeName="width" from="0" to="195" begin="24s" dur="3s" fill="freeze"/></rect></g>`+
      T(430,80,13,"0.07 s","cr",25,40)+T(430,125,13,"1.0 s","cr",27,40)+T(400,165,16,"No protection: Red guesses the secret 98-100% of the time","cr",28,40,"middle","700")+
      `<g opacity="0">${show(41,62)}<rect x="200" y="62" width="0" height="24" rx="4" class="fg"><animate attributeName="width" from="0" to="562" begin="42s" dur="4s" fill="freeze"/></rect><rect x="200" y="107" width="0" height="24" rx="4" class="fg"><animate attributeName="width" from="0" to="562" begin="42s" dur="4s" fill="freeze"/></rect><line x1="762" y1="52" x2="762" y2="140" stroke-width="3" class="sg"/></g>`+
      T(762,160,12,"fixed reply time (3 s)","cg",46,62,"end")+T(400,200,16,"Fixed window: both look the same to Red","cg",47,62,"middle","700")+
      T(400,235,14,"Real model: 42-47% normal prompts (50% = guessing)","t",50,62,"middle")+T(400,258,14,"57.5% long answers, 58.3% under a flood: bounded, NOT proven safe","ca",54,62,"middle","700");
   // c) cache 62-82
   s+=T(400,30,20,"Model cache: does a repeated prompt answer faster?","t",62.3,82,"middle","700")+T(30,90,14,"Shared cache","m",62.5,82)+T(30,150,14,"Own cache per run","m",62.5,82)+
      `<g opacity="0">${show(63,82)}<rect x="200" y="72" width="0" height="26" rx="4" class="fr"><animate attributeName="width" from="0" to="${5.6*95}" begin="64s" dur="2.5s" fill="freeze"/></rect><rect x="200" y="132" width="0" height="26" rx="4" class="fg"><animate attributeName="width" from="0" to="${5.6*46}" begin="64s" dur="2.5s" fill="freeze"/></rect><line x1="${200+5.6*50}" y1="60" x2="${200+5.6*50}" y2="175" stroke-width="2" stroke-dasharray="5 4" class="sm"/></g>`+
      T(740,92,14,"95%","cr",67,82,"end","700")+T(440,150,14,"45-48%","cg",67,82,"start","700")+T(480,190,12,"50% = Red is only guessing","m",67,82,"middle")+
      T(400,235,15,"Each run gets its own cache area: leak gone (mock).","cg",70,82,"middle","700");
   // d) flood 82-105
   s+=T(400,30,20,"Flood: Red sends a huge number of requests","t",82.3,105,"middle","700")+T(30,90,14,"Audit queue before fix","m",82.5,105)+T(30,150,14,"Audit queue after fix","m",82.5,105)+
      `<g opacity="0">${show(83,105)}<rect x="200" y="72" width="0" height="26" rx="4" class="fr"><animate attributeName="width" from="0" to="560" begin="84s" dur="3s" fill="freeze"/></rect><rect x="200" y="132" width="0" height="26" rx="4" class="fg"><animate attributeName="width" from="0" to="2" begin="84s" dur="3s" fill="freeze"/></rect></g>`+
      T(210,128,14,"10,000 waiting (queue full)","cr",87,105,"start","700")+T(210,176,14,"35 waiting","cg",87,105,"start","700")+
      T(400,225,15,"Bug found: one stuck connection froze the whole audit queue.","t",90,105,"middle")+T(400,248,15,"Fix: a fresh connection after any failure. Blue's replies no longer slow down (local test).","cg",94,105,"middle","700");
   return svg(s)}},
{name:"5 Useful feedback",dur:35,cap:"A defence that hides everything is useless: Red must still find real weak spots. There is a trade-off, and we measured the optional meter only in simulation.",
 draw:()=>svg(T(400,30,20,"Does Red still get useful feedback? (probes needed to find a planted bypass)","t",0.3,0,"middle","700")+T(30,100,14,"No protection (exact)","m",1)+T(30,170,14,"Our meter, no noise","m",1)+
   GROW(220,82,5.6*7,28,"fg",2,2)+GROW(220,152,5.6*60,28,"fa",5,4)+T(260,102,15,"7 probes","cg",4,0,"start","700")+T(560,172,15,"60 probes (8-9x more)","ca",9,0,"start","700")+
   T(400,225,15,"The meter still lets a targeted attacker tell rule A from B (100%), with 15% noise 89%.","t",14,0,"middle")+
   T(400,255,15,"Simulation with a mock model. Default report: NOT measured yet.","cr",20,0,"middle","700")+T(400,300,14,"More protection means weaker attacks. That is a real trade-off.","m",26,0,"middle"))},
{name:"6 Scoreboard",dur:40,cap:"Of eleven attack groups, seven were stopped, four reduced but not closed, and one more is out of scope. Small tests, mostly mock, one laptop.",
 draw:()=>{let s=T(400,30,20,"Scoreboard: 11 attack groups tested","t",0.3,0,"middle","700");
   const G=["Network","Files","Fake tokens","Error messages","Model cache","Log search","Flood (local)"],A=["Timing (real 58%)","Final report","CPU-load slip","Docker flood"];
   G.forEach((n,i)=>{const x=20+(i%4)*195,y=55+Math.floor(i/4)*60;s+=`<g opacity="0">${show(2+i*1.5)}<rect x="${x}" y="${y}" width="185" height="48" rx="8" class="fg"/><text x="${x+92}" y="${y+30}" font-size="15" font-weight="700" fill="#fff" text-anchor="middle">${n}</text></g>`});
   A.forEach((n,i)=>{const x=20+i*195,y=190;s+=`<g opacity="0">${show(15+i*1.5)}<rect x="${x}" y="${y}" width="185" height="48" rx="8" class="fa"/><text x="${x+92}" y="${y+30}" font-size="15" font-weight="700" fill="#fff" text-anchor="middle">${n}</text></g>`});
   s+=`<g opacity="0">${show(23)}<rect x="20" y="252" width="760" height="44" rx="8" class="fk"/><text x="400" y="280" font-size="15" font-weight="700" fill="#fff" text-anchor="middle">Out of scope: kernel escape, hardware and GPU side channels, compromised gateway</text></g>`;
   return svg(s+T(110,326,14,"7 stopped","cg",27,0,"middle","700")+T(400,326,14,"4 reduced, not closed","ca",29,0,"middle","700")+T(690,326,14,"1 out of scope","m",31,0,"middle","700"))}},
{name:"7 Close",dur:20,cap:"That was Hide, Normalize, Prove by Team Ctrl Alt. Code, tests and all results are on our GitHub, in the prototype folder. Thank you.",
 draw:()=>svg(T(400,110,36,"Hide, Normalize, Prove","t",0.5,0,"middle","700")+T(400,150,20,"Team Ctrl Alt","m",1.5,0,"middle")+T(400,215,17,"We do not say it is secure.","cr",4,0,"middle","700")+T(400,243,17,"We say exactly what we measured.","cg",6,0,"middle","700")+
   T(400,300,14,"github.com/MdTabish24/hide-normalize-prove  (prototype folder)","m",9,0,"middle"))}
];
const tabs=document.getElementById("tabs"),stage=document.getElementById("stage"),cap=document.getElementById("cap"),clock=document.getElementById("clock"),playBtn=document.getElementById("play");
let cur=0,playing=true,timer=null;
function load(n){
  cur=Math.max(0,Math.min(SCENES.length-1,n));
  tabs.querySelectorAll("button").forEach((b,k)=>b.classList.toggle("on",k===cur));
  stage.innerHTML=SCENES[cur].draw(); cap.textContent=SCENES[cur].cap;
  const sv=document.getElementById("sv"); if(!playing) sv.pauseAnimations();
}
function tick(){
  const sv=document.getElementById("sv"); if(!sv) return;
  const t=sv.getCurrentTime(); clock.textContent=`${SCENES[cur].name}: ${Math.min(t,SCENES[cur].dur).toFixed(0)} / ${SCENES[cur].dur} s`;
  if(playing && t>=SCENES[cur].dur){ if(cur<SCENES.length-1) load(cur+1); else {playing=false;sv.pauseAnimations();playBtn.textContent="Replay"} }
}
SCENES.forEach((s,k)=>{const b=document.createElement("button");b.textContent=s.name;b.onclick=()=>load(k);tabs.appendChild(b)});
playBtn.onclick=()=>{const sv=document.getElementById("sv");
  if(playBtn.textContent==="Replay"){playing=true;playBtn.textContent="Pause";load(0);return}
  playing=!playing; playBtn.textContent=playing?"Pause":"Play"; playing?sv.unpauseAnimations():sv.pauseAnimations()};
document.getElementById("prev").onclick=()=>load(cur-1);document.getElementById("next").onclick=()=>load(cur+1);
document.addEventListener("keydown",e=>{if(e.key==="ArrowRight")load(cur+1);if(e.key==="ArrowLeft")load(cur-1);if(e.key===" "){e.preventDefault();playBtn.click()}});
setInterval(tick,250); load(0);
