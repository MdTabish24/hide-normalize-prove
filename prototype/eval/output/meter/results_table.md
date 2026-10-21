# Feedback meter: leakage vs utility

Label: simulated (production meter code). Parameters fixed in PARAMS.md (v1) before this run. 50% leak accuracy = this attacker could not tell A from B; it is not proof of no leak.

| Arm | Red's A-vs-B accuracy (unseen runs, 95% Wilson) | Finds planted bypass within 150 probes | Median / mean probes (successes) | Median reads |
|---|---:|---:|---:|---:|
| none | 50.0% (44.4%-55.6%), n=300 | 10.3% (7.4%-14.3%), n=300 | 0 / 0 | 0 |
| exact | 100.0% (98.7%-100.0%), n=300 | 100.0% (98.7%-100.0%), n=300 | 7.0 / 6.5 | 0.0 |
| meter q=0 | 100.0% (98.7%-100.0%), n=300 | 100.0% (98.7%-100.0%), n=300 | 60.0 / 55.3 | 4.0 |
| meter q=0.15 | 89.0% (85.0%-92.1%), n=300 | 68.7% (63.2%-73.7%), n=300 | 60.0 / 59.9 | 4.0 |
| meter repeated reads | 50.0% (44.4%-55.6%), n=300 | NOT RUN | n/a | NOT RUN |
