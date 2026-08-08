# Setu — Demo Script

**Runtime:** 4 minutes + 2 minutes Q&A
**Roles:** Palak = narrator · Sanvi = driver (laptop)

> **Rule:** the narrator never touches the laptop, the driver never talks. Two people
> talking over one screen is what makes hackathon demos look amateur.

**Two-person adjustments:** the phone for Moment 5 sits on the table on speaker —
a judge dials it themselves, so nobody needs to hold it. Sanvi keeps the backup
video cued in a second tab and switches to it without narration if something dies.
Palak handles all Q&A; Sanvi stays on the laptop and pulls up whatever a judge asks
to see.

---

## Before you walk in — the pre-flight

Run this checklist 10 minutes before. Every item is something that has killed a demo.

- [ ] `VOICE_MODE=offline` — demo audio pre-cached, no live ASR gamble
- [ ] `DEMO_MODE=true` — seeded DB, 5 personas at different case stages
- [ ] Backend running, one query already fired through it (warm the model — first
      Granite call is always slow and it will look broken)
- [ ] Browser at 125% zoom, one tab, bookmarks bar hidden, notifications OFF
- [ ] Phone on the table, screen unlocked, ringer ON, connected to hotspot not venue wifi
- [ ] Backup video open in a second tab, ready to play
- [ ] **Airplane-mode rehearsal done at least once**
- [ ] Vendor consent footage cued to the right timestamp

---

## The story you are telling

> Ramesh sells pani puri from a cart. He has run this business for nine years.
> Every bank considers him uncreditworthy — not because he is, but because
> nobody has ever counted what he earns.
>
> Setu doesn't tell him he's ineligible. It shows him the path, fixes what's
> broken, and builds the proof he never had.

Say this in your own words, not memorised. If you sound like you're reciting, you lose the room.

---

## MOMENT 0 — Open on the real person (20 seconds)

**Palak:** *"Before we show you software, meet Ramesh. He's real, we spent an
afternoon with him, and everything you're about to see runs on his actual words."*

▶ Play the 15-second vendor clip.

> **Why this first:** no competing team will have a real user. It buys you
> credibility for everything after, and it stops judges evaluating you as a
> student project.

---

## MOMENT 1 — Speak (40 seconds)

**Sanvi:** clicks the mic, plays Ramesh's cached audio.

On screen: live transcript in Devanagari → structured profile card fills in.

**Palak:** *"He spoke for eight seconds, in Hindi, about his cart. No form, no
fields, no English. Granite pulled out his occupation, his daily takings, his
location, and which documents he actually has."*

**Properties demonstrated**
| Property | What it proves |
|---|---|
| Voice-first input | No literacy required |
| Vernacular (Hindi) | No English gatekeeping |
| Unstructured → structured | Granite tool-calling, strict JSON |
| Document inventory | Feeds the ladder and Doc Doctor downstream |

---

## MOMENT 2 — The Ladder ★ (70 seconds — your centrepiece, do not rush)

On screen: PM SVANidhi card. Status is **not** a red "ineligible" — it's a path
with rungs.

**Palak:** *"Here's where every other tool stops. It would say: you don't
qualify, you're missing a Certificate of Vending. Full stop. Setu says something
different."*

**Sanvi:** expands the ladder.

> **Step 1** — Letter of Recommendation from the Town Vending Committee · ₹0 · ~7 days
> **Step 2** — Open PM SVANidhi application with the LoR · ₹0 · same day
> **→ Unlocks ₹15,000 at 7% interest subsidy, then ₹25,000, then ₹50,000**

**Palak:** *"Two steps. Zero rupees. About a week. That's the difference between
'you're ineligible' and a person actually getting money."*

**Sanvi:** clicks **"Why?"** on step 1.

On screen: the exact rule that fired, the values compared, and **the highlighted
line from the official PM SVANidhi Operational Guidelines PDF.**

**Palak:** *"Every decision traces to a real government document. The model
didn't decide he was eligible — a rule engine did, and Granite only explained it
in his language. Same input gives a byte-identical trace, every time. Nothing
here is hallucinated, because the model was never in the decision seat."*

**Properties demonstrated**
| Property | What it proves |
|---|---|
| **Counterfactual path search** | The single most differentiated feature |
| Remedy metadata (₹ + days) | Actionable, not just informative |
| Deterministic rule engine | LLM never decides eligibility |
| RAG citation to source span | Auditable, not "trust me" |
| Trust Ledger trace | Replayable, byte-identical |

> **If a judge interrupts here, let them.** This is the feature you want them
> asking questions about.

---

## MOMENT 3 — The Catch (45 seconds)

**Sanvi:** photographs Ramesh's Aadhaar and bank passbook (use the real blurred
scans).

On screen: red flag — **name mismatch.** `RAMESH KUMAR` vs `RAMESH KUMAAR`.

**Palak:** *"This is real, from his actual documents. If he'd applied, this
application would have been rejected in about three months — and nobody would
have told him why. He'd have assumed the scheme wasn't for people like him. We
caught it in four seconds, before he applied."*

**Properties demonstrated**
| Property | What it proves |
|---|---|
| Granite Vision + Docling extraction | Multimodal, IBM stack |
| Cross-document consistency check | Addresses the *actual* failure mode |
| Pre-submission catch | Prevention, not diagnosis |

---

## MOMENT 4 — The Trust Passport ★ (50 seconds)

**Sanvi:** hits the time-warp switch → 30 days of Ramesh's spoken daily takings.

**Palak:** *"Every evening he speaks for five seconds. 'Aaj aath sau ka kaam
hua, do sau ka maal liya.' That's it."*

**Sanvi:** clicks **Generate Statement** → bank-readable cash-flow PDF opens:
revenue trend, margin, seasonality, consistency score.

**Palak:** *"Thirty days ago no lender could underwrite him. This is a document a
loan officer can actually read. He wasn't uncreditworthy — nobody was counting.
And he owns this file. He can take it to any bank, with or without us."*

**Properties demonstrated**
| Property | What it proves |
|---|---|
| Voice ledger | Zero-literacy bookkeeping |
| Alternative credit identity | Attacks the "no credit history" constraint |
| User-owned, portable artifact | Not lock-in; genuine empowerment |
| Compounding inclusion | The Round 1 claim, made mechanical |

---

## MOMENT 5 — The Call (40 seconds — the closer)

**Palak:** *"Ramesh has a smartphone. Millions don't. Give us a missed call from
your own phone — any of you."*

Judge dials the number and hangs up. **Setu calls back within seconds** and
speaks to them in Hindi through the room speaker.

**Palak:** *"It costs him nothing. No data, no app, no smartphone, no literacy.
One phone number on a wall poster is our entire onboarding funnel."*

> **If telephony fails:** don't apologise, don't fumble. Say *"here's the same
> flow running the production state machine"* and drive the in-browser IVR
> simulator. It is identical code. Move on at normal pace.

**Properties demonstrated**
| Property | What it proves |
|---|---|
| Missed-call callback | ₹0 to the user — real field knowledge |
| Feature-phone reach | Serves who "AI for inclusion" tools quietly exclude |
| Channel-agnostic core | Same engine, same trace, three surfaces |

---

## CLOSE — The dashboard + the line (25 seconds)

**Sanvi:** opens the dashboard — users reached, ₹ unlocked, match rate,
**fairness audit sliced by gender / caste category / state / language**, top
coverage gaps.

**Palak:** *"We measured ourselves. 40 test personas, precision and recall on the
board, and a bias audit across four slices — because a system that decides who
gets money should be audited, not trusted. The gaps at the bottom are schemes
nobody has written yet. That's a policy brief for a government, and it's our
second customer."*

**The closing line — land this cleanly and stop talking:**

> *"Setu isn't a scheme finder. Setu makes invisible people underwritable.
> Ramesh went from uncreditworthy to two steps and seven days away from ₹15,000
> — and he never read a single word."*

---

## Full property inventory

Everything Setu does, grouped. Use this for Q&A and for the deck, not as a
spoken list.

### Access
- Voice-first input, no forms
- Vernacular (Hindi, Marathi, + others via the same pipeline)
- Zero-literacy UI — icons over text, every control speaks itself
- Missed-call callback (₹0, feature phone, no data)
- WhatsApp channel
- PWA, offline-capable, low-bandwidth

### Intelligence
- Granite profile extraction: unstructured speech → strict JSON
- Deterministic eligibility engine — three-valued (eligible / not / need-info)
- **Counterfactual path search — the ladder**, costed in ₹ and days
- RAG grounded in Docling + Data Prep Kit ingested government documents
- Bounded agentic tool loop (checklist → prefill → reminder)
- Granite Vision document extraction

### Trust
- Every decision cites a source document and span
- Trust Ledger — signed, replayable, byte-identical traces
- LLM never decides eligibility, only translates
- "Why?" explanation on every recommendation
- Human escalation path for low-confidence cases
- PII redaction at ingestion (IBM Data Prep Kit)
- Fairness audit across gender / caste / state / language
- 40-persona eval with published precision and recall

### Follow-through
- Case tracker: pending documents, deadlines, status
- Standing eligibility — re-evaluated forever, unprompted callback
- Document Doctor — cross-document consistency before submission
- Prefilled application PDF + document checklist
- Voice Ledger → bank-readable cash-flow statement
- Fraud Shield — states real cost, flags extortion

### Sustainability
- Lenders pay for verified, document-complete leads
- Free to users, permanently
- Demand Signal → policy briefs for government
- Coverage-gap learning expands the knowledge base

---

## Q&A prep — the questions you will actually get

**"How do you know the eligibility rules are correct?"**
> They're hand-authored from official guidelines PDFs, each rule carries the
> source document and span, and they're unit-tested. We show the citation on
> screen. We deliberately took the LLM out of the decision — it can't invent a
> rule it isn't allowed to write.

**"What if the ASR mishears him?"**
> Two protections. The profile is shown back and confirmed before any decision.
> And missing fields return NEED_INFO rather than a guess — we never fill a
> blank with a plausible value.

**"Isn't this just myScheme with voice?"**
> myScheme tells you what you qualify for today. It has no answer for the 80%
> who don't qualify yet, no view of why applications actually fail, and no way to
> reach someone without a smartphone. The ladder, the Doc Doctor, and the missed
> call are all things it structurally cannot do.

**"How does this make money?"**
> Lenders pay for verified, document-complete leads — that's an existing market,
> and MSME credit demand is ₹25 lakh crore unmet. Users never pay.

**"What's the accuracy?"**
> [Your real number] precision across 40 personas, plus disparate-impact numbers
> across four demographic slices. Give the real figure. **Never inflate it — one
> checked claim that's wrong costs more than a modest number honestly stated.**

**"Did you build this in 36 hours?"**
> Yes, and here's what's real versus roadmap: [be precise]. Judges respect a
> clean line between the two far more than a blurred one.

**"What about privacy?"**
> PII redacted at ingestion, no raw audio retained, consent recorded on camera
> from our field user, and he can have his data deleted. Financial decisions
> escalate to a human, never full automation.

---

## Honesty rules — non-negotiable

1. **Never demo a mock as if it's live.** Say "this part is stubbed" and move on.
   Judges catch it, and it poisons everything else you showed.
2. **Never claim a component you didn't use.** If Bhashini didn't come through,
   say "local Whisper with a Bhashini adapter ready" — that's a better answer
   than a claim that collapses under one question.
3. **Quote your real eval numbers**, however modest.
4. **If something breaks, say so plainly and continue.** Composure reads as
   competence; flustered apologising reads as a project held together with tape.

---

## Timing

| Segment | Time | Running |
|---|---|---|
| Real person | 0:20 | 0:20 |
| Speak | 0:40 | 1:00 |
| **Ladder** | **1:10** | 2:10 |
| The Catch | 0:45 | 2:55 |
| Trust Passport | 0:50 | 3:45 |
| The Call | 0:40 | 4:25 |
| Close | 0:25 | 4:50 |

Over 4 minutes? **Cut the Catch, not the Ladder.** The ladder is the submission.

Rehearse out loud twice. Not in your head — out loud, with the laptop, timed.
