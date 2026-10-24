# Demo video transcript with screen plan (about 5 minutes, easy English)

Team: **Ctrl Alt Elite**. Project: **Hide, Normalize, Prove**.

## Before you record
1. Start the dashboard from the `prototype` folder: `python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8090 --no-access-log`
2. Open `http://127.0.0.1:8090/play` in the browser, press **Ctrl + F5**, make the window full screen, zoom 100%.
3. Do one practice run through every button, so you know how long each simulation takes (about 5 seconds).
4. How the page works: the buttons on top choose the screen. The big green button (or **Space**) runs both panels together. **Next** (or the right arrow) goes to the next attack. Left panel (red) = without our solution. Right panel (green) = with our solution.

## Screen plan at a glance
| Part | What you say | Screen to show | Click |
|---|---|---|---|
| 1 Intro | who we are | **Overview** | nothing yet |
| 2 Problem | what can leak | **Overview**, left panel | **Run** |
| 3 What we built | the guard design | **Overview**, right panel | **Run** again |
| 4a Direct doors | network, files, tokens, errors | **1 Network**, **2 Files**, **3 Tokens**, **4 Errors** | **Run** on each, then **Next** |
| 4b Timing | the clock | **5 Timing** | **Run** |
| 4c Cache and logs | cache, files | **6 Cache**, **8 Logs** | **Run** on each |
| 4d Flood | the audit bug | **9 Flood** | **Run** |
| 5 Feedback | does Red still learn | **Feedback** | **Run** |
| 6 Scoreboard | 7 / 4 / 1 | **7 Report**, **10 CPU**, **11 Docker**, then **Score** | **Run** on each, then on Score |
| 7 Close | thank you | **Score** (stay) | nothing |

## 1. Intro (0:00 - 0:25)
*Screen: **Overview**. Do not click Run yet.*

"Hi, we are Team Ctrl Alt Elite. Our project is called Hide, Normalize, Prove. It answers Bayora's challenge: how can a Red team, a Blue team and a client LLM share one sandbox, without anyone leaking secrets to anyone else?"

## 2. The problem (0:25 - 0:55)
*Screen: **Overview**. Press **Run** as you start the first sentence. Point at the LEFT panel: Red's six arrows (network, timing, errors, cache, load, logs) go to the secret rule.*

"Red tries to attack. Blue has a private filter with a secret rule. If Red can learn that rule from anything it can see, the whole safety test is worthless. And it is not only the network. Red can learn from timing, from error messages, from the model's cache, from system load, even from log files. We wanted to find all these doors and close them."

## 3. What we built (0:55 - 1:30)
*Screen: **Overview**. Press **Run** again. Point at the RIGHT panel: Red reaches only the guard, the same reply comes back.*

"Everything runs in Docker. Red is locked in its own network and can only talk to a gateway. The gateway is the guard: Red always gets the same short reply, at the same time, whatever happens inside. Blue's filter is private. The model is clean, and its cache is separate for every run. And every event goes into a signed audit book, so any edit is detected."

## 4. Eleven attacks (1:30 - 3:15)
Always the same rhythm: click the button, press **Run**, say the sentence while the panels play, point first at the red panel, then at the green one.

**4a. Direct doors (about 40 seconds)**
*Screen: **1 Network** -> Run. Then **2 Files** -> Run. Then **3 Tokens** -> Run. Then **4 Errors** -> Run.*

"To test this, we built eleven attacks ourselves and measured each one.

First, the direct doors: network, files and secrets, fake tokens, and error messages. All four were stopped. And something we are proud of: for the network, the secrets and the logs we also built deliberately weak setups, for example Red attached to every network. Our tests caught the leak every time. So these tests really can see a leak."

*On "weak setups" go back to the red panel of **1 Network** (the arrows reach Blue, the model and the audit) and say: "this is the weak setup".*
*On **3 Tokens** say: "for this one we did not build a weak setup, so the left panel says not measured."*

**4b. Timing (about 30 seconds)**
*Screen: **5 Timing** -> Run. Point at the left bars (0.07 s against 1.0 s), then at the right bars (both 3.0 s).*

"Next, timing. Without protection, Red guesses Blue's secret rule 98 to 100 percent of the time, even with the real DeepSeek model. With our fixed-window design, on normal prompts Red gets only 33 to 47 percent across four runs. Fifty percent means Red is just guessing. But with long answers it is 57.5 percent, and under a flood of requests it is 58.3 percent. So we call this bounded, not safe."

**4c. Cache and logs (about 20 seconds)**
*Screen: **6 Cache** -> Run. Then **8 Logs** -> Run.*

"The model cache leak went from 95 percent to 45 percent. Searching logs and files found no plain prompt, only hashes."

**4d. Flood (about 20 seconds)**
*Screen: **9 Flood** -> Run. Point at the left bars (911 to 1811 ms), then the right bars (909 to 910 ms).*

"Then the flood. We found a real bug: one stuck connection froze our whole audit queue. We fixed it, and the queue went from ten thousand waiting events to thirty-five. Blue's replies no longer slow down when Red floods the gateway, in our local test."

## 5. Does Red still get useful feedback? (3:15 - 3:50)
*Screen: **Feedback** -> Run. Point at the left bar (7 probes), then the right bar (60 probes).*

"A defence that hides everything is useless. Red must still find real weak spots. With no protection, Red finds a planted bypass in seven probes. With our meter, it needs about sixty probes, and it can still tell the secret rule apart. So there is a real trade-off. And we want to be honest: we measured this only for our optional meter, in simulation. For the default report we have not measured it yet."

## 6. The honest scoreboard (3:50 - 4:30)
*Screen: while you say "four were reduced", click **5 Timing**, **7 Report**, **10 CPU**, **11 Docker** one after another (no need to wait for the whole animation, just show the amber badge). Then click **Score** and press **Run** on "one more group is out of scope".*

"Here is our final score. Of eleven attack groups, seven were stopped. Four were reduced but not closed: timing, the final report, CPU load, and a Docker flood. One more group is out of scope: kernel escapes, hardware and GPU side channels. We checked that Red's container has no special rights, but we did not try real exploits.

These are small tests, mostly with a mock model, on one laptop. We wrote every test setting before running it, and every result file is on GitHub. We do not say our system is secure. We say exactly what we measured."

## 7. Close (4:30 - 4:50)
*Screen: stay on **Score**.*

"That was Hide, Normalize, Prove, by Team Ctrl Alt Elite. The code, the test files and all results are on our GitHub, in the prototype folder. Thank you."

---
## Do say / do not say
- Say: "stopped" for 7 attacks, "reduced, not closed" for 4, "out of scope" for 1.
- Say: "single runs, mostly mock model, one laptop".
- Do not say: "secure", "zero leakage", "9 of 12", "we solved everything", "timing is stopped".
- If asked about attack 3 (fake tokens): "stopped in our test, but we did not build a weak setup to prove that test can fail".
- If asked about the real-model flood: "58.3 percent, interval 45.7 to 69.9, so we cannot claim it is better than the default".
- If a judge asks about one attack: click its button and press Run, the text under the panels explains what our solution actually does, and `/room` has the long cards.
