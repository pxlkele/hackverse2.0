# Language review sheet

**Read every line ALOUD, and listen to its audio file.** These are spoken by a
machine to someone who cannot read the screen, so how it *sounds* is the whole
test — a sentence can be grammatical and still be wrong for this.

Setu's eight languages were translated by an AI and **have not been checked by
a speaker**. Everything is verified mechanically (speech in, correct rupee
figures out); what is unverified is whether it sounds like a person.

## What to ask, for each line

1. **Would you say it this way out loud?** Not "is it correct" — formal written
   phrasing is the common failure. This is a phone call, not a form.
2. **Are the keypad numbers right?** "Press one" must use the spoken numeral a
   caller would recognise. Same for hash / star.
3. **Is anything too long?** A listener cannot scroll back. If they lose the
   thread halfway, cut it.
4. **Do the scheme names sound right left in English?** PM SVANidhi, FSSAI,
   PMSBY, PMJJBY stay in Latin **on purpose** — that is what a bank clerk will
   recognise. Confirm that reads naturally rather than jarring.
5. **Does the voice pronounce it correctly?** Separate question from the text.
   edge-tts can mangle a correct sentence. This is why you listen, not just read.

Mark each line **OK** or write the replacement. Partial feedback is still useful —
one language reviewed properly beats eight skimmed.

## Play a whole language, in call order

Sit the reviewer down and run this once. It plays the prompts in the order a real
caller hears them, so they judge the flow and not just the sentences:

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path[:0] = ['.', 'services/api']
from channels import ivr_sim
from services.api.core import voice
LANG = "kn"          # <- change this
for key in ["ask_situation", "thinking", "after_answer",
            "case_opened", "operator", "not_understood", "nothing_heard"]:
    text = ivr_sim.PROMPTS[key].get(LANG)
    if not text:
        continue
    print(f"\n[{key}]\n{text}")
    input("  enter to play, then note anything wrong… ")
    voice.play(voice.speak(text, LANG))
EOF
```

It reads from the same cache the demo plays from, so what they hear is exactly
what a caller hears.

**After any change:** edit `PROMPTS` in `channels/ivr_sim.py`, then re-cache, or
the new wording will be silent with the wifi off:

```bash
.venv/bin/python -c "import sys; sys.path[:0]=['.','services/api']; \
from channels import ivr_sim; print(ivr_sim.precache_prompts())"
.venv/bin/python -m pytest -q
```

---


## Hindi — `hi`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> बीप के बाद बताइए, आप क्या काम करते हैं और आपको किस चीज़ की ज़रूरत है। जैसे — मैं सब्ज़ी बेचता हूँ, मुझे लोन चाहिए। बताने के बाद हैश दबाइए।

`afplay services/api/data/voice_cache/8de20611fec866d9d406.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> एक मिनट रुकिए। मैं सरकारी नियम देख रहा हूँ।

`afplay services/api/data/voice_cache/2454c29e437757da9035.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> फिर से सुनने के लिए एक दबाइए। आवेदन शुरू करने के लिए दो दबाइए। किसी व्यक्ति से बात करने के लिए शून्य दबाइए।

`afplay services/api/data/voice_cache/1fa982139dda56e3a404.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> आपका आवेदन शुरू हो गया है। हम आपको याद दिलाने के लिए फ़ोन करेंगे। फ़ोन रखने के लिए नौ दबाइए।

`afplay services/api/data/voice_cache/20f1524cc72c51ccc4f2.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> आपको आपके नज़दीकी सी. एस. सी. केंद्र के ऑपरेटर से जोड़ा जा रहा है। वे आपके कागज़ देखने में मदद करेंगे।

`afplay services/api/data/voice_cache/f63bde4d0d4ba9fe16b8.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> माफ़ कीजिए, मैं समझ नहीं पाया। दोबारा कोशिश करने के लिए एक दबाइए।

`afplay services/api/data/voice_cache/2007f57f8f2eedd1538b.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> मुझे कुछ सुनाई नहीं दिया। दोबारा बोलने के लिए एक दबाइए।

`afplay services/api/data/voice_cache/bf7a95365dc3c0f22944.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

| field | shown as | what it labels |
|---|---|---|
| `label` | हिं | this language's own chip |
| `prompt` | अपने बारे में बताइए | under the big button, before speaking |
| `talk` | बोलिए | the big button |
| `stop` | रोकिए | the button while recording |
| `listening` | सुन रहे हैं… | status while recording |
| `thinking` | सरकारी नियम देख रहे हैं… | status while the rules run |
| `replay` | फिर से सुनिए | play the answer again |
| `human` | किसी व्यक्ति से बात करें | talk to a person |
| `err` | दोबारा कोशिश कीजिए | something went wrong |
| `free` | मुफ़्त | a step that costs nothing |
| `days` | दिन | how long a step takes |
| `steps` | कदम | rungs on the ladder |
| `denied` | माइक की इजाज़त दीजिए | microphone permission refused |
| `insecure` | यह पेज सुरक्षित नहीं है | page not served over HTTPS |

- [ ] screen labels all OK   ·   fixes: ______________________________

---

## English — `en`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> After the beep, tell us what work you do and what you need. For example — I sell vegetables, I need a loan. Press hash when you finish.

`afplay services/api/data/voice_cache/cae7c21ca88c5eeb7b93.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> One moment. I am checking the government rules.

`afplay services/api/data/voice_cache/92a94d6316a4a7ce4a44.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> To hear that again, press one. To start your application, press two. To speak to a person, press zero.

`afplay services/api/data/voice_cache/8a0fcf0e06c00e1c9e32.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> Your application has been started. We will call you with reminders. Press nine to hang up.

`afplay services/api/data/voice_cache/8769768c8fc482f5f9f2.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> Connecting you to an operator at your nearest C S C centre. They will help you check your documents.

`afplay services/api/data/voice_cache/405bba6b4a633e7ee2bb.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> Sorry, I did not understand that. Press one to try again.

`afplay services/api/data/voice_cache/4525224680fa11b68f73.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> I did not hear anything. Press one to speak again.

`afplay services/api/data/voice_cache/2c1c782359ea6329d3bc.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

| field | shown as | what it labels |
|---|---|---|
| `label` | EN | this language's own chip |
| `prompt` | Tell us about your work | under the big button, before speaking |
| `talk` | Speak | the big button |
| `stop` | Stop | the button while recording |
| `listening` | Listening… | status while recording |
| `thinking` | Checking government rules… | status while the rules run |
| `replay` | Play again | play the answer again |
| `human` | Talk to a person | talk to a person |
| `err` | Please try again | something went wrong |
| `free` | free | a step that costs nothing |
| `days` | days | how long a step takes |
| `steps` | steps | rungs on the ladder |
| `denied` | Please allow the microphone | microphone permission refused |
| `insecure` | This page needs HTTPS for the mic | page not served over HTTPS |

- [ ] screen labels all OK   ·   fixes: ______________________________

---

## Marathi — `mr`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> बीप नंतर सांगा, तुम्ही काय काम करता आणि तुम्हाला काय हवं आहे. जसं — मी भाजी विकतो, मला कर्ज हवं आहे. सांगून झाल्यावर हॅश दाबा.

`afplay services/api/data/voice_cache/0a70e6bec4256cc49140.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> एक मिनिट थांबा. मी सरकारी नियम पाहत आहे.

`afplay services/api/data/voice_cache/ed221b7e6c8aea362493.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> पुन्हा ऐकण्यासाठी एक दाबा. अर्ज सुरू करण्यासाठी दोन दाबा. एखाद्या व्यक्तीशी बोलण्यासाठी शून्य दाबा.

`afplay services/api/data/voice_cache/bde7434c739279db648d.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> तुमचा अर्ज सुरू झाला आहे. आम्ही तुम्हाला आठवण करून देण्यासाठी फोन करू. फोन ठेवण्यासाठी नऊ दाबा.

`afplay services/api/data/voice_cache/a556570f4d7efaf34f9c.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> तुम्हाला तुमच्या जवळच्या सी. एस. सी. केंद्रातील ऑपरेटरशी जोडत आहोत. ते तुमचे कागद पाहण्यात मदत करतील.

`afplay services/api/data/voice_cache/60037a1c5985b23f3403.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> माफ करा, मला समजलं नाही. पुन्हा प्रयत्न करण्यासाठी एक दाबा.

`afplay services/api/data/voice_cache/de4029d6fda513b3291e.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> मला काही ऐकू आलं नाही. पुन्हा बोलण्यासाठी एक दाबा.

`afplay services/api/data/voice_cache/fd70b610a4e1e687b5a9.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

| field | shown as | what it labels |
|---|---|---|
| `label` | मराठी | this language's own chip |
| `prompt` | तुमच्याबद्दल सांगा | under the big button, before speaking |
| `talk` | बोला | the big button |
| `stop` | थांबा | the button while recording |
| `listening` | ऐकत आहोत… | status while recording |
| `thinking` | सरकारी नियम पाहत आहोत… | status while the rules run |
| `replay` | पुन्हा ऐका | play the answer again |
| `human` | एखाद्या व्यक्तीशी बोला | talk to a person |
| `err` | पुन्हा प्रयत्न करा | something went wrong |
| `free` | मोफत | a step that costs nothing |
| `days` | दिवस | how long a step takes |
| `steps` | पायऱ्या | rungs on the ladder |
| `denied` | माइकची परवानगी द्या | microphone permission refused |
| `insecure` | हे पेज सुरक्षित नाही | page not served over HTTPS |

- [ ] screen labels all OK   ·   fixes: ______________________________

---

## Gujarati — `gu`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> બીપ પછી કહો, તમે શું કામ કરો છો અને તમને શું જોઈએ છે. જેમ કે — હું શાકભાજી વેચું છું, મને લોન જોઈએ છે. કહી લીધા પછી હેશ દબાવો.

`afplay services/api/data/voice_cache/06d5510566db3fb52363.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> એક મિનિટ રોકાઓ. હું સરકારી નિયમો જોઈ રહ્યો છું.

`afplay services/api/data/voice_cache/8ce92f0b458fbe8dfab8.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> ફરી સાંભળવા માટે એક દબાવો. અરજી શરૂ કરવા માટે બે દબાવો. કોઈ વ્યક્તિ સાથે વાત કરવા માટે શૂન્ય દબાવો.

`afplay services/api/data/voice_cache/57296d40d73d1669c0a8.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> તમારી અરજી શરૂ થઈ ગઈ છે. અમે તમને યાદ કરાવવા ફોન કરીશું. ફોન મૂકવા માટે નવ દબાવો.

`afplay services/api/data/voice_cache/4adf3cbb4adc3102b8b8.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> તમને તમારા નજીકના સી. એસ. સી. કેન્દ્રના ઓપરેટર સાથે જોડી રહ્યા છીએ. તેઓ તમારા કાગળ જોવામાં મદદ કરશે.

`afplay services/api/data/voice_cache/610c9005ad8e3b21063c.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> માફ કરો, મને સમજાયું નહીં. ફરી પ્રયત્ન કરવા માટે એક દબાવો.

`afplay services/api/data/voice_cache/cdc4c1ea397a054b33fe.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> મને કંઈ સંભળાયું નહીં. ફરી બોલવા માટે એક દબાવો.

`afplay services/api/data/voice_cache/c7d3614664a68116a8d8.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

| field | shown as | what it labels |
|---|---|---|
| `label` | ગુજરાતી | this language's own chip |
| `prompt` | તમારા વિશે કહો | under the big button, before speaking |
| `talk` | બોલો | the big button |
| `stop` | રોકો | the button while recording |
| `listening` | સાંભળી રહ્યા છીએ… | status while recording |
| `thinking` | સરકારી નિયમો જોઈ રહ્યા છીએ… | status while the rules run |
| `replay` | ફરી સાંભળો | play the answer again |
| `human` | કોઈ વ્યક્તિ સાથે વાત કરો | talk to a person |
| `err` | ફરી પ્રયત્ન કરો | something went wrong |
| `free` | મફત | a step that costs nothing |
| `days` | દિવસ | how long a step takes |
| `steps` | પગલાં | rungs on the ladder |
| `denied` | માઇકની પરવાનગી આપો | microphone permission refused |
| `insecure` | આ પેજ સુરક્ષિત નથી | page not served over HTTPS |

- [ ] screen labels all OK   ·   fixes: ______________________________

---

## Bengali — `bn`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> বীপের পরে বলুন, আপনি কী কাজ করেন এবং আপনার কী দরকার। যেমন — আমি সবজি বিক্রি করি, আমার ঋণ দরকার। বলা শেষ হলে হ্যাশ চাপুন।

`afplay services/api/data/voice_cache/1edc3be51eb95c58a13a.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> এক মিনিট অপেক্ষা করুন। আমি সরকারি নিয়ম দেখছি।

`afplay services/api/data/voice_cache/c9a2089782ccafbbb08e.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> আবার শুনতে এক চাপুন। আবেদন শুরু করতে দুই চাপুন। কারও সঙ্গে কথা বলতে শূন্য চাপুন।

`afplay services/api/data/voice_cache/0db0dac689cde7e13747.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> আপনার আবেদন শুরু হয়েছে। আমরা আপনাকে মনে করিয়ে দিতে ফোন করব। ফোন রাখতে নয় চাপুন।

`afplay services/api/data/voice_cache/213cfc5dfe8b54a4c9ac.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> আপনাকে আপনার নিকটতম সি. এস. সি. কেন্দ্রের অপারেটরের সঙ্গে যোগ করা হচ্ছে। তাঁরা আপনার কাগজ দেখতে সাহায্য করবেন।

`afplay services/api/data/voice_cache/2f849e1283d5df35f7cb.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> দুঃখিত, আমি বুঝতে পারিনি। আবার চেষ্টা করতে এক চাপুন।

`afplay services/api/data/voice_cache/a5bcdbe4cb24b339c501.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> আমি কিছু শুনতে পাইনি। আবার বলতে এক চাপুন।

`afplay services/api/data/voice_cache/a7d13ced3a1851e09699.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

| field | shown as | what it labels |
|---|---|---|
| `label` | বাংলা | this language's own chip |
| `prompt` | আপনার কথা বলুন | under the big button, before speaking |
| `talk` | বলুন | the big button |
| `stop` | থামুন | the button while recording |
| `listening` | শুনছি… | status while recording |
| `thinking` | সরকারি নিয়ম দেখছি… | status while the rules run |
| `replay` | আবার শুনুন | play the answer again |
| `human` | কারও সঙ্গে কথা বলুন | talk to a person |
| `err` | আবার চেষ্টা করুন | something went wrong |
| `free` | বিনামূল্যে | a step that costs nothing |
| `days` | দিন | how long a step takes |
| `steps` | ধাপ | rungs on the ladder |
| `denied` | মাইকের অনুমতি দিন | microphone permission refused |
| `insecure` | এই পেজ সুরক্ষিত নয় | page not served over HTTPS |

- [ ] screen labels all OK   ·   fixes: ______________________________

---

## Tamil — `ta`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> பீப் சத்தத்திற்குப் பிறகு சொல்லுங்கள், நீங்கள் என்ன வேலை செய்கிறீர்கள், உங்களுக்கு என்ன தேவை. உதாரணமாக — நான் காய்கறி விற்கிறேன், எனக்கு கடன் வேண்டும். சொல்லி முடித்ததும் ஹாஷ் அழுத்துங்கள்.

`afplay services/api/data/voice_cache/a0782bb66d2a31e8c525.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> ஒரு நிமிடம் காத்திருங்கள். நான் அரசு விதிகளைப் பார்க்கிறேன்.

`afplay services/api/data/voice_cache/e2f696e612e4d047a70e.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> மீண்டும் கேட்க ஒன்று அழுத்துங்கள். விண்ணப்பத்தைத் தொடங்க இரண்டு அழுத்துங்கள். ஒருவருடன் பேச பூஜ்ஜியம் அழுத்துங்கள்.

`afplay services/api/data/voice_cache/b812f22de4d2b449baa3.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> உங்கள் விண்ணப்பம் தொடங்கிவிட்டது. நினைவூட்ட நாங்கள் அழைப்போம். அழைப்பை முடிக்க ஒன்பது அழுத்துங்கள்.

`afplay services/api/data/voice_cache/502ae30bf405ad97c066.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> உங்கள் அருகிலுள்ள சி. எஸ். சி. மையத்தின் ஆபரேட்டருடன் இணைக்கிறோம். அவர்கள் உங்கள் ஆவணங்களைப் பார்க்க உதவுவார்கள்.

`afplay services/api/data/voice_cache/82dd6cb64e1c481423a8.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> மன்னிக்கவும், எனக்குப் புரியவில்லை. மீண்டும் முயற்சிக்க ஒன்று அழுத்துங்கள்.

`afplay services/api/data/voice_cache/d931ea36dd79a633988c.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> எனக்கு எதுவும் கேட்கவில்லை. மீண்டும் பேச ஒன்று அழுத்துங்கள்.

`afplay services/api/data/voice_cache/d1e8275ce611ea9823ba.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

| field | shown as | what it labels |
|---|---|---|
| `label` | தமிழ் | this language's own chip |
| `prompt` | உங்களைப் பற்றி சொல்லுங்கள் | under the big button, before speaking |
| `talk` | பேசுங்கள் | the big button |
| `stop` | நிற்க | the button while recording |
| `listening` | கேட்கிறோம்… | status while recording |
| `thinking` | அரசு விதிகளைப் பார்க்கிறோம்… | status while the rules run |
| `replay` | மீண்டும் கேளுங்கள் | play the answer again |
| `human` | ஒருவருடன் பேசுங்கள் | talk to a person |
| `err` | மீண்டும் முயற்சிக்கவும் | something went wrong |
| `free` | இலவசம் | a step that costs nothing |
| `days` | நாட்கள் | how long a step takes |
| `steps` | படிகள் | rungs on the ladder |
| `denied` | மைக் அனுமதி தாருங்கள் | microphone permission refused |
| `insecure` | இந்தப் பக்கம் பாதுகாப்பானது அல்ல | page not served over HTTPS |

- [ ] screen labels all OK   ·   fixes: ______________________________

---

## Telugu — `te`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> బీప్ తర్వాత చెప్పండి, మీరు ఏ పని చేస్తారు, మీకు ఏమి కావాలి. ఉదాహరణకు — నేను కూరగాయలు అమ్ముతాను, నాకు రుణం కావాలి. చెప్పిన తర్వాత హాష్ నొక్కండి.

`afplay services/api/data/voice_cache/eebc1612cc9857926bef.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> ఒక నిమిషం ఆగండి. నేను ప్రభుత్వ నియమాలు చూస్తున్నాను.

`afplay services/api/data/voice_cache/41dff88e1dc6354ed8d2.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> మళ్ళీ వినడానికి ఒకటి నొక్కండి. దరఖాస్తు ప్రారంభించడానికి రెండు నొక్కండి. ఒక వ్యక్తితో మాట్లాడటానికి సున్నా నొక్కండి.

`afplay services/api/data/voice_cache/11bd2ff819677c8d0198.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> మీ దరఖాస్తు ప్రారంభమైంది. గుర్తు చేయడానికి మేము ఫోన్ చేస్తాము. ఫోన్ పెట్టేయడానికి తొమ్మిది నొక్కండి.

`afplay services/api/data/voice_cache/228b10ae42498d845a8d.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> మీ దగ్గరి సి. ఎస్. సి. కేంద్రం ఆపరేటర్‌తో కలుపుతున్నాము. వారు మీ పత్రాలు చూడటానికి సహాయం చేస్తారు.

`afplay services/api/data/voice_cache/788fd6a12aeb760c020f.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> క్షమించండి, నాకు అర్థం కాలేదు. మళ్ళీ ప్రయత్నించడానికి ఒకటి నొక్కండి.

`afplay services/api/data/voice_cache/4daa39ef69e55e246587.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> నాకు ఏమీ వినిపించలేదు. మళ్ళీ మాట్లాడటానికి ఒకటి నొక్కండి.

`afplay services/api/data/voice_cache/f8dcbbe5502ed8f16edb.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

| field | shown as | what it labels |
|---|---|---|
| `label` | తెలుగు | this language's own chip |
| `prompt` | మీ గురించి చెప్పండి | under the big button, before speaking |
| `talk` | మాట్లాడండి | the big button |
| `stop` | ఆపండి | the button while recording |
| `listening` | వింటున్నాము… | status while recording |
| `thinking` | ప్రభుత్వ నియమాలు చూస్తున్నాము… | status while the rules run |
| `replay` | మళ్ళీ వినండి | play the answer again |
| `human` | ఒక వ్యక్తితో మాట్లాడండి | talk to a person |
| `err` | మళ్ళీ ప్రయత్నించండి | something went wrong |
| `free` | ఉచితం | a step that costs nothing |
| `days` | రోజులు | how long a step takes |
| `steps` | అడుగులు | rungs on the ladder |
| `denied` | మైక్ అనుమతి ఇవ్వండి | microphone permission refused |
| `insecure` | ఈ పేజీ సురక్షితం కాదు | page not served over HTTPS |

- [ ] screen labels all OK   ·   fixes: ______________________________

---

## Kannada — `kn`

### Spoken prompts (the phone call)

**`ask_situation`** — The main question. The caller hears this first and answers it out loud.

> ಬೀಪ್ ನಂತರ ಹೇಳಿ, ನೀವು ಏನು ಕೆಲಸ ಮಾಡುತ್ತೀರಿ ಮತ್ತು ನಿಮಗೆ ಏನು ಬೇಕು. ಉದಾಹರಣೆಗೆ — ನಾನು ತರಕಾರಿ ಮಾರುತ್ತೇನೆ, ನನಗೆ ಸಾಲ ಬೇಕು. ಹೇಳಿದ ನಂತರ ಹ್ಯಾಶ್ ಒತ್ತಿ.

`afplay services/api/data/voice_cache/cc9eab16614296686d16.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`thinking`** — Played while the rules are being checked.

> ಒಂದು ನಿಮಿಷ ಕಾಯಿರಿ. ನಾನು ಸರ್ಕಾರಿ ನಿಯಮಗಳನ್ನು ನೋಡುತ್ತಿದ್ದೇನೆ.

`afplay services/api/data/voice_cache/a8784f8fdf52f9e6330d.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`after_answer`** — The menu after an answer. Keypad digits matter here.

> ಮತ್ತೆ ಕೇಳಲು ಒಂದು ಒತ್ತಿ. ಅರ್ಜಿ ಪ್ರಾರಂಭಿಸಲು ಎರಡು ಒತ್ತಿ. ಒಬ್ಬ ವ್ಯಕ್ತಿಯೊಂದಿಗೆ ಮಾತನಾಡಲು ಸೊನ್ನೆ ಒತ್ತಿ.

`afplay services/api/data/voice_cache/f9d1ed397b96caf5d06d.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`case_opened`** — Confirmation that an application was started.

> ನಿಮ್ಮ ಅರ್ಜಿ ಪ್ರಾರಂಭವಾಗಿದೆ. ನೆನಪಿಸಲು ನಾವು ಫೋನ್ ಮಾಡುತ್ತೇವೆ. ಫೋನ್ ಇಡಲು ಒಂಬತ್ತು ಒತ್ತಿ.

`afplay services/api/data/voice_cache/37722041235a7e8d6bb9.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`operator`** — Handing off to a human at a CSC centre.

> ನಿಮ್ಮ ಹತ್ತಿರದ ಸಿ. ಎಸ್. ಸಿ. ಕೇಂದ್ರದ ಆಪರೇಟರ್‌ಗೆ ಜೋಡಿಸುತ್ತಿದ್ದೇವೆ. ಅವರು ನಿಮ್ಮ ದಾಖಲೆಗಳನ್ನು ನೋಡಲು ಸಹಾಯ ಮಾಡುತ್ತಾರೆ.

`afplay services/api/data/voice_cache/7d62d3238f9365ca3b57.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`not_understood`** — ASR returned something unusable.

> ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಲು ಒಂದು ಒತ್ತಿ.

`afplay services/api/data/voice_cache/ca18ec36c8762c518746.mp3`

- [ ] OK   ·   replacement: ______________________________________

**`nothing_heard`** — ASR returned nothing at all.

> ನನಗೆ ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ. ಮತ್ತೆ ಮಾತನಾಡಲು ಒಂದು ಒತ್ತಿ.

`afplay services/api/data/voice_cache/8deeb4f2c316200078c2.mp3`

- [ ] OK   ·   replacement: ______________________________________

### On-screen labels (the app)

- [ ] screen labels all OK   ·   fixes: ______________________________

---
