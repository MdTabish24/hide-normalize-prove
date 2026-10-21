# System ko seedhe shabdon me samjho (10 minute)

## Kahani
Ek exam hall hai. **Red** mushkil sawal poochkar AI ko fasana chahta hai. **Blue** ek chhupa hua filter lagata hai jo kuch sawal rok deta hai. **AI** (model) jawab deta hai.
Red ko Blue ka filter nahi pata hona chahiye, warna wo uski kamzori dhoond lega. Aur Blue ko Red ke sawal pehle nahi dikhne chahiye.
Teeno ek hi computer par chalte hain. **Hamara kaam:** chhupa raha bhi sahi, aur baad me saabit bhi kar sako ki kuch nahi bigda.

## Dibbe (Docker containers)
```
 red-client  ──►  GATEWAY (guard)  ──►  blue-defense (filter check karta hai)
 (attacker)            │          └──►  model-mock (nakli AI, ya real DeepSeek)
                       └──────────►  audit-collector (diary: har event sign karke likhta hai)
```
- **Red sirf gateway se baat kar sakta hai.** Blue, model, audit ya internet tak raasta hi nahi. (11/11 checks.)
- **Gateway sab sambhalta hai:** Red ka prompt leta hai, Blue ka rule (encrypted) kholta hai, prompt aur rule blue-defense ko bhejta hai, allowed ho to model ko bhejta hai, aur Red ko jawab ek fixed time par deta hai.
- **blue-defense sirf check karta hai** (rule gateway se aata hai, wahan store nahi hota).
- **audit-collector diary hai:** har event hash chain me, signature ke saath. Ek line badlo to chain tut jati hai.

## Ek request ki kahani (7 step)
1. Red gateway ko prompt bhejta hai.
2. Gateway **ghadi chalu** karta hai aur Blue se check karwata hai.
3. Blue **block ya allow** decide karta hai. Block ho to model tak nahi jata.
4. Allowed ho to model jawab banata hai.
5. **Red ko hamesha wahi milta hai:** `202`, `{"status":"pending"}`, 64 bytes, **fixed time par.** Chahe prompt block hua ho ya allow.
6. Test khatam hone par asli result ek sealed report me jata hai. Red ko sirf **halka noisy range** milta hai.
7. Har kadam audit diary me likha jata hai.

## Teen cheezein jinse sab banta hai
- **Hide (chhupao):** Red ko Blue ka rule, Blue ko Red ka sawal na dikhe. Alag networks, encryption, sab kuch gateway se.
- **Normalize (ek jaisa karo):** Red ko jo kuch bhi dikhta hai (jawab, size, time) wo block aur allow dono me ek jaisa ho.
- **Prove (saabit karo):** audit diary + naapne ka tarika (do secret A aur B ke saath wahi test chalao aur dekho Red kuch pakad pata hai ya nahi).

## Leak kaise hota hai (sabse zaroori idea)
Red ko Blue ka secret tab pata chalta hai jab **Red jo dekh sakta hai wo Blue ke rule ke hisaab se badalta hai.**
- Bina defense me: blocked prompt model tak nahi jata, **jaldi lautta hai** (0.05 s). Allowed der se (0.27 s). Red **ghadi dekhkar** pakad leta hai.
- Hamare fix me: sab ka jawab **ek hi fixed time par** (0.93 s). Ghadi se kuch nahi pata chalta.
- Isliye "pending" akela kaafi nahi hota. Bina defense me bhi Red ko "pending" hi milta tha, leak **time** se hota tha.

## "Red ki guess" ka matlab
Red sirf dekh kar guess karta hai ki Blue ka rule A hai ya B. **50% = sikka uchhalna** (kuch pata nahi). **100% = secret pakad liya.**
- Bina defense: ~98-100%. Hamare solution ke saath: ~46-56%.
- Ye mock model par, ek laptop par, time ko 10 guna chhota karke naapa gaya hai.

## Do tarah ke system
- **raw:** jawab ready hote hi bhej do. (Bina defense.)
- **window_hard + continue:** sab ko ek hi fixed time par pending. Lambi request cancel nahi hoti, peeche chalti rehti hai. (Hamara solution, opt-in.)

## Kya solve hua, kya nahi (ek line me)
- **Hua:** network band, error se pehchan, time se pehchan (aam traffic), cache guess, files/logs, audit tamper (7/7), real model par chhota run.
- **Nahi hua:** CPU load wali bheed (jab audit fix ke bina), noisy report ka average, hosted model ka cache, Blue ka Red ke payload dekh pana (test hi nahi hua).

## Khud ko test karo (jawab neeche, pehle khud likho)
1. Red kis se baat kar sakta hai aur kis se nahi?
2. Gateway ka kaam kya hai? (3 cheezein)
3. Bina defense me Red ko "pending" milta tha to leak kahan se hota tha?
4. 50% ka matlab kya hai?
5. Fixed window me lambi request ko cancel kyun nahi karte, aur uski kimat kya hai?
6. Blue ka filter kahan chalta hai aur rule kahan store hai?
7. Audit me ek line badlo to kya hota hai?
8. Humne kya test **nahi** kiya? (kam se kam 3)

### Jawab
1. Sirf gateway. Blue, model, audit, internet nahi.
2. Blue ka rule sambhalna aur check karwana; model tak sirf allowed prompt bhejna; Red ko fixed time par ek jaisa jawab dena (aur audit events likhna).
3. **Time** se: block hone par jawab jaldi aata tha, allow hone par der se.
4. Red ko farak pata nahi chala, sikka uchhalne jaisa. Ye saboot nahi ki leak hai hi nahi.
5. Cancel karne par sab ek jaisi cancel hoti thi to 50% bekar ho jata tha ("kuch deliver hi nahi hua"). Kimat: model peeche chalta rehta hai (resource), aur hard maximum (4x window) ke baad cancel hoti hai.
6. Filter blue-defense dibbe me chalta hai; rule gateway me encrypted rehta hai aur har request par prompt ke saath bheja jata hai.
7. Hash chain tut jati hai, verifier INVALID bolta hai (7/7 cases me pakda gaya).
8. Real model par bada test; CPU/noisy neighbour (pura); Blue ka Red ka payload dekhna; hosted cache; kernel/hardware; kai Red identities (Sybil).
