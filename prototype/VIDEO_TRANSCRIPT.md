# Demo video transcript (about 5 minutes, easy English)

Team: **Ctrl Alt**. Project: **Hide, Normalize, Prove**. Show the dashboard page `/room` while you talk. Say the numbers exactly as written.

## 1. Intro (0:00 - 0:25)
*On screen: the Room page, attack 1.*

"Hi, we are Team Ctrl Alt. Our project is called Hide, Normalize, Prove. It answers Bayora's challenge: how can a Red team, a Blue team and a client LLM share one sandbox, without anyone leaking secrets to anyone else?"

## 2. The problem (0:25 - 0:55)

"Red tries to attack. Blue has a private filter with a secret rule. If Red can learn that rule from anything it can see, the whole safety test is worthless. And it is not only the network. Red can learn from timing, from error messages, from the model's cache, from system load, even from log files. We wanted to find all these doors and close them."

## 3. What we built (0:55 - 1:30)
*On screen: the five boxes of the room.*

"Everything runs in Docker. Red is locked in its own network and can only talk to a gateway. The gateway is the guard: Red always gets the same short reply, at the same time, whatever happens inside. Blue's filter is private. The model is clean, and its cache is separate for every run. And every event goes into a signed audit book, so any edit is detected."

## 4. Eleven attacks (1:30 - 3:15)
*On screen: click through the numbered cards.*

"To test this, we built eleven attacks ourselves and measured each one.

First, the direct doors: network, files and secrets, fake tokens, and error messages. All four were stopped. And here is something we are proud of: for the network, the secrets and the logs we also built deliberately weak setups, for example Red attached to every network. Our tests caught the leak every time. So these tests really can see a leak.

Next, timing. Without protection, Red guesses Blue's secret rule 98 to 100 percent of the time, even with the real DeepSeek model. With our fixed-window design, on normal prompts Red gets only 42 to 47 percent. Fifty percent means Red is just guessing. But with long answers it is 57.5 percent, and under a flood of requests it is 58.3 percent. So we call this bounded, not safe.

The model cache leak went from 95 percent to 45 percent. Searching logs and files found no plain prompt, only hashes.

Then the flood. We found a real bug: one stuck connection froze our whole audit queue. We fixed it, and the queue went from ten thousand waiting events to thirty-five. Blue's replies no longer slow down when Red floods the gateway, in our local test."

## 5. Does Red still get useful feedback? (3:15 - 3:50)
*On screen: the Feedback card.*

"A defence that hides everything is useless. Red must still find real weak spots. With no protection, Red finds a planted bypass in seven probes. With our meter, it needs about sixty probes, and it can still tell the secret rule apart. So there is a real trade-off. And we want to be honest: we measured this only for our optional meter, in simulation. For the default report we have not measured it yet."

## 6. The honest scoreboard (3:50 - 4:30)
*On screen: the Score card.*

"Here is our final score. Of eleven attack groups, seven were stopped. Four were reduced but not closed: timing, the final report, CPU load, and a Docker flood. One more group is out of scope: kernel escapes, hardware and GPU side channels. We checked that Red's container has no special rights, but we did not try real exploits.

These are small tests, mostly with a mock model, on one laptop. We wrote every test setting before running it, and every result file is on GitHub. We do not say our system is secure. We say exactly what we measured."

## 7. Close (4:30 - 4:50)

"That was Hide, Normalize, Prove, by Team Ctrl Alt. The code, the test files and all results are on our GitHub, in the prototype folder. Thank you."

---
## Do say / do not say
- Say: "stopped" for 7 attacks, "reduced, not closed" for 4, "out of scope" for 1.
- Say: "single runs, mostly mock model, one laptop".
- Do not say: "secure", "zero leakage", "9 of 12", "we solved everything", "timing is stopped".
- If asked about attack 3 (fake tokens): "stopped in our test, but we did not build a weak gateway to prove that test can fail".
- If asked about real-model flood: "58.3 percent, interval 45.7 to 69.9, so we cannot claim it is better than the default".
