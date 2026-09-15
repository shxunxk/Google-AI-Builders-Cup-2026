# Immune City
### A Self-Hardening, Explainable Fraud Immune System for India's Digital Payments
**Google AI Builders Cup 2026 — BFSI Track**

---

## 1. Mission Statement

Google already publishes a fraud-investigator agent pattern: Gemini pulls similar past cases and evidence, then produces a verdict on a suspicious transaction. It works — but it has two honest gaps:

1. **Not explainable enough to dispute.** It says "flagged," not "here's exactly why, and here's what would have made it not flagged." Regulators and customers can't contest a black-box verdict.
2. **Static, not adaptive.** Fraud rings evolve their tactics constantly; the detection logic doesn't evolve with them unless a human manually updates it.

Meanwhile, UPI carries the majority of India's digital payment volume, and digital-arrest scams and mule-account networks are a live, Supreme-Court-flagged national problem — one explicitly called out as a place AI/ML should be doing more.

**Immune City takes Google's existing fraud-agent pattern and fixes both gaps, aimed squarely at that real problem**: it explains itself in a way that can be argued and disputed, it hardens itself against adapting fraud rings automatically, and it shows the *whole network* of fraud forming — not just one transaction at a time.

---

## 2. The Three Pillars (your judging checklist)

| # | Pillar | Gap it fixes | What it looks like |
|---|--------|---------------|---------------------|
| 1 | **The Courtroom** — argued, disputable verdicts | Not explainable/defensible | Prosecutor agent vs. Defense agent argue a flagged transaction; Judge agent delivers a verdict + counterfactual ("would not be flagged if X") |
| 2 | **The Duel** — self-hardening detection | Static detection | Attacker agent generates new fraud patterns to beat the Defender; Defender updates its own rules/retrieval after each successful attack — visibly gets smarter live |
| 3 | **FinCity** — systemic, not case-by-case | Only sees one transaction at a time | A live animated network graph of thousands of synthetic accounts; fraud rings visually cluster and light up as they form; time slider shows a ring growing over days |

Each pillar is a standalone demo moment. Build in this order — if you run out of time, you still have a complete, coherent story after Pillar 1 or 2.

---

## 3. Architecture Overview

```
                     ┌─────────────────────────┐
                     │   Synthetic UPI City     │
                     │   (BigQuery-generated)   │
                     └────────────┬────────────┘
                                  │
                          Pub/Sub (transaction stream)
                                  │
                    ┌─────────────▼─────────────┐
                    │      Cloud Run: Scorer      │
                    │  (Vertex AI classifier)     │
                    └─────────────┬───────────────┘
                                  │ flagged
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                    ▼
     ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐
     │ Defender Agent   │  │ Attacker Agent  │  │ FinCity Graph     │
     │ (Gemini + ADK)   │◄─┤ (Gemini + ADK)  │  │ Engine (Cloud Run │
     │ Vertex AI Search │  │ generates new   │  │ + BigQuery graph  │
     │ (policy grounding)│  │ fraud patterns  │  │ queries)          │
     │ Document AI      │  └────────────────┘  └──────────────────┘
     │ (KYC/doc parsing)│
     └────────┬─────────┘
              │
     ┌────────▼─────────┐
     │  Courtroom Agent   │
     │  Prosecutor +       │
     │  Defense + Judge     │
     │  (Gemini, 3 roles)   │
     └────────┬─────────┘
              │
     ┌────────▼─────────┐
     │ Counterfactual      │
     │ Explainer            │
     │ (Gemini + feature    │
     │ attribution)          │
     └────────┬─────────┘
              │
     ┌────────▼──────────────────────┐
     │  Firestore (case/session state) │
     │  Cloud Run (web app frontend)    │
     │  Looker Studio (risk dashboard)  │
     │  Speech-to-Text/TTS/Translation  │
     │  (multilingual query channel)     │
     └───────────────────────────────────┘
```

---

## 4. Full Google Tool Map (why each is there, not just checkbox usage)

| Tool | Role | Free tier notes |
|---|---|---|
| **Google AI Studio (Gemini API)** | Fast prototyping of all agent prompts before porting to Vertex AI | Free, no billing account needed — use this first |
| **Vertex AI + Agent Development Kit (ADK)** | Hosts the Defender, Attacker, Prosecutor/Defense/Judge agents in production form | Covered by $300 trial credit |
| **BigQuery** | Synthetic transaction/city generation, storage, analytics, graph adjacency queries | 1TB queries/mo + 10GB storage free forever |
| **BigQuery ML** | `ML.FORECAST` for spend/risk trend lines shown on the dashboard; `ML.GENERATE_TEXT` for quick in-SQL summaries | Inside BigQuery free allowance |
| **Vertex AI (classifier)** | The first-pass anomaly scorer that decides what gets escalated to the agents | Trial credit |
| **Vertex AI Search / Agent Search** | Grounds the Defender and Prosecutor's arguments in real policy/compliance text, so they cite rules instead of hallucinating | Small corpus stays well within credit |
| **Document AI** | Parses KYC forms/loan docs referenced in case files | Free monthly page quota |
| **Pub/Sub** | Simulates the live transaction stream feeding the whole system | Free tier covers demo volume |
| **Cloud Run** | Hosts the scorer service, the agents' API layer, and the FinCity graph frontend — scales to zero | Effectively free at demo scale |
| **Firestore** | Stores case history, session state, and the evolving "threat genome" log from the duel | Generous free tier |
| **Speech-to-Text / Text-to-Speech** | Lets a "customer" report suspicious activity by voice, in a live demo moment | Free tier covers a demo |
| **Cloud Translation** | Makes the query channel work in Hindi/regional languages — ties into financial inclusion | Free tier |
| **Looker Studio** | The "bank risk officer" dashboard: fraud caught, false-positive rate, duel history over time | Free, connects directly to BigQuery |
| **Dataflow** *(optional, cut first if short on time)* | Only if you want a visible pipeline step for judges; not essential to the core story | — |

---

## 5. Data Plan

You do **not** need real bank data — this is entirely simulatable, which removes your biggest risk:

- Generate a synthetic "city" of ~2,000–5,000 accounts in BigQuery: customers, merchants, a handful of seeded mule-account rings.
- Generate a baseline transaction stream with normal patterns (BigQuery SQL + a Python generator script is enough).
- Hand-author 10–15 "golden" fraud scenarios modeled on real, publicly reported patterns: digital-arrest scam transfers, mule-account layering, synthetic identity loan fraud. These become your rehearsed demo moments.
- Let the Attacker Agent generate additional, *unscripted* fraud patterns live during the duel — this is what makes the "self-hardening" moment feel real rather than canned.

---

## 6. 25-Day Build Plan

### Phase 1 — Foundation (Days 1–5)
- Day 1: Finalize scope, set up GCP project, enable billing/trial credit, register for any hackathon-specific credit code.
- Day 2: Design BigQuery schema (accounts, transactions, documents, case log). Write the synthetic city generator.
- Day 3: Generate baseline synthetic transaction stream; load into BigQuery; set up Pub/Sub topic + Cloud Run subscriber skeleton.
- Day 4: Build the first-pass Vertex AI classifier (simple, e.g. gradient boosted model) on the synthetic data.
- Day 5: Wire classifier into the Pub/Sub → Cloud Run pipeline end to end. **Checkpoint: transactions flow in, get scored, flagged ones logged.**

### Phase 2 — Pillar 1: The Courtroom (Days 6–10)
- Day 6: Prototype Prosecutor/Defense/Judge prompts in Google AI Studio using a handful of golden fraud cases.
- Day 7: Stand up Vertex AI Search over a small synthetic policy/compliance corpus; ground Prosecutor/Judge citations in it.
- Day 8: Port agents to Vertex AI + ADK; wire to real BigQuery data (not hardcoded examples).
- Day 9: Build counterfactual explainer (use feature attribution from the classifier + Gemini to phrase it in plain language).
- Day 10: Build the Courtroom UI (two argument panels + verdict card) as a Cloud Run web app. **Checkpoint: a flagged transaction can be fully tried and produces a disputable verdict.**

### Phase 3 — Pillar 2: The Duel (Days 11–15)
- Day 11: Design the Attacker Agent prompt/loop: reads recent Defender decisions, proposes a new evasion pattern.
- Day 12: Build the feedback loop: Attacker's pattern is injected into the transaction stream, scored, and the outcome (caught or missed) logged to Firestore.
- Day 13: Build the Defender's self-update step: on a miss, it updates its Vertex AI Search corpus or prompt rules to close the gap.
- Day 14: Build the "threat evolution timeline" visualization (round-by-round log, rendered as a simple timeline/graph).
- Day 15: Run and tune the duel for 20–30 rounds until you have a genuinely compelling, watchable evolution. **Checkpoint: live loop visibly improves over rounds.**

### Phase 4 — Pillar 3: FinCity (Days 16–20)
- Day 16: Decide graph scale target (start at a few hundred nodes, not thousands). Choose a force-graph rendering library (e.g. D3.js or a WebGL library) for the Cloud Run frontend.
- Day 17: Write BigQuery graph/adjacency queries to compute account relationships and ring clusters.
- Day 18: Build the base animated graph view (nodes, edges, pulsing activity).
- Day 19: Layer in fraud-ring highlighting and the time slider (scrub through days to watch a ring form).
- Day 20: Wire click-through: clicking a node opens a case file (Pillar 1), clicking a cluster opens the courtroom for its worst transaction. **Checkpoint: the three pillars are now one connected experience.**

### Phase 5 — Polish, Breadth, Rehearsal (Days 21–25)
- Day 21: Add Speech-to-Text/TTS + Cloud Translation query channel (only if core is stable — cut first under time pressure).
- Day 22: Build the Looker Studio dashboard (fraud caught, false-positive rate, duel history) connected to BigQuery.
- Day 23: Full run-through; fix rough edges; write the pitch deck (mission → gap → three pillars → evidence).
- Day 24: Record a backup demo video (protects you if live demo/network fails on the day).
- Day 25: Final rehearsal, timing the demo to the pitch slot; prepare answers for "how does this compare to Google's own reference pattern" (your mission statement *is* the answer).

---

## 7. Pitch Structure (for the actual presentation)

1. **Open with the existing state of the art**: Google's own fraud-investigator agent pattern — show you know the field, not just your own idea.
2. **Name the two honest gaps**: not explainable/disputable, not adaptive.
3. **Name the real-world stakes**: UPI scale, digital-arrest scams, Supreme Court commentary — this is not a toy problem.
4. **Show, don't tell, in this order**: FinCity (scale/spectacle) → click into a cluster → Courtroom (explainability) → cut to the Duel timeline (adaptiveness).
5. **Close with the Google tool map** as evidence of full-stack execution, not just a slide of logos.

---

## 8. Risk Mitigation

- **Graph rendering is the highest-risk engineering piece** — scope to hundreds of nodes first; only scale up if time allows (Day 16 decision point).
- **Live demo failure risk** — always have a recorded backup video (Day 24).
- **Agent reliability under live conditions** — rehearse with 3–4 pre-validated "golden" scenarios you know work, and let the *unscripted* duel be the only fully-live improvisational element.
- **Scope creep** — if behind schedule by Day 15, cut Phase 5 breadth items (voice/translation, Dataflow) before cutting any of the three pillars.
