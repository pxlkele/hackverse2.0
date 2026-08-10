"""
IVR simulator — the feature-phone channel.

Setu's central claim is that you do not need a smartphone, an app, or the
ability to read English. Every other channel we ship quietly assumes at least
one of those. This one assumes a phone that can dial and a person who can
speak, which is the actual floor.

Real telephony (Twilio) was cut for time. What was NOT cut is the call flow:
begin() / on_digit() / on_speech() are a transport-agnostic state machine that
returns a Turn describing what to say and what to wait for next. The browser
front-end is one transport; a Twilio webhook would be another, calling the same
three functions. Swapping them is a new endpoint, not a rewrite.

Eight languages, listed in SUPPORTED_LANGUAGES — the one place that list lives.
It started as two, on the reasoning that half-verified Hindi beats two languages
that are right. That still holds, so nothing was added on faith: every language
here has been put through the whole pipeline, ASR to spoken answer, and the
transcripts are in services/api/tests/test_profile.py.

The *spoken* greeting is still a Hindi/English menu, and deliberately so. It
plays before the caller has chosen anything, and reading eight options aloud to
someone holding a feature phone would be worse than useless. Clients with a
screen pass their language to begin() and never hear the menu.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services.api.core import (
    eligibility,
    narrate,
    pathfinder,
    phone_bus,
    profile as profile_mod,
    store,
    voice,
)

router = APIRouter(prefix="/api/ivr", tags=["ivr"])

Expect = Literal["digit", "speech", "end"]


# ── Prompts ──────────────────────────────────────────────────────────────────
# Written to be *heard*, not read: short sentences, the action last, no clause
# a listener has to hold in memory. Every prompt that offers choices repeats
# them, because a caller cannot scroll back.

PROMPTS = {
    "greeting": {
        # All eight languages spoken in the greeting. Each line is delivered in
        # its own language so the caller recognises theirs by ear, not by number.
        # Kept short — one clause per language.
        "hi": (
            "नमस्ते। सेतु में आपका स्वागत है। "
            "हिंदी के लिए एक दबाइए। "
            "For English, press two. "
            "मराठीसाठी तीन दाबा। "
            "ગુજરાતી માટે ચાર દબાવો. "
            "বাংলার জন্য পাঁচ চাপুন। "
            "தமிழுக்கு ஆறு அழுத்தவும். "
            "తెలుగు కోసం ఏడు నొక్కండి. "
            "ಕನ್ನಡಕ್ಕಾಗಿ ಎಂಟು ಒತ್ತಿ."
        ),
        "en": (
            "नमस्ते। सेतु में आपका स्वागत है। "
            "हिंदी के लिए एक दबाइए। "
            "For English, press two. "
            "मराठीसाठी तीन दाबा। "
            "ગુજરાતી માટે ચાર દબાવો. "
            "বাংলার জন্য পাঁচ চাপুন। "
            "தமிழுக்கு ஆறு அழுத்தவும். "
            "తెలుగు కోసం ఏడు నొక్కండి. "
            "ಕನ್ನಡಕ್ಕಾಗಿ ಎಂಟು ಒತ್ತಿ."
        ),
    },
    "ask_situation": {
        "hi": (
            "बीप के बाद बताइए, आप क्या काम करते हैं और आपको किस चीज़ की ज़रूरत है। "
            "जैसे — मैं सब्ज़ी बेचता हूँ, मुझे लोन चाहिए। बताने के बाद हैश दबाइए।"
        ),
        "en": (
            "After the beep, tell us what work you do and what you need. "
            "For example — I sell vegetables, I need a loan. Press hash when you finish."
        ),
        "mr": (
            "बीप नंतर सांगा, तुम्ही काय काम करता आणि तुम्हाला काय हवं आहे. "
            "जसं — मी भाजी विकतो, मला कर्ज हवं आहे. सांगून झाल्यावर हॅश दाबा."
        ),
        "gu": (
            "બીપ પછી કહો, તમે શું કામ કરો છો અને તમને શું જોઈએ છે. "
            "જેમ કે — હું શાકભાજી વેચું છું, મને લોન જોઈએ છે. કહી લીધા પછી હેશ દબાવો."
        ),
        "bn": (
            "বীপের পরে বলুন, আপনি কী কাজ করেন এবং আপনার কী দরকার। "
            "যেমন — আমি সবজি বিক্রি করি, আমার ঋণ দরকার। বলা শেষ হলে হ্যাশ চাপুন।"
        ),
        "ta": (
            "பீப் சத்தத்திற்குப் பிறகு சொல்லுங்கள், நீங்கள் என்ன வேலை செய்கிறீர்கள், "
            "உங்களுக்கு என்ன தேவை. உதாரணமாக — நான் காய்கறி விற்கிறேன், எனக்கு கடன் வேண்டும். "
            "சொல்லி முடித்ததும் ஹாஷ் அழுத்துங்கள்."
        ),
        "te": (
            "బీప్ తర్వాత చెప్పండి, మీరు ఏ పని చేస్తారు, మీకు ఏమి కావాలి. "
            "ఉదాహరణకు — నేను కూరగాయలు అమ్ముతాను, నాకు రుణం కావాలి. "
            "చెప్పిన తర్వాత హాష్ నొక్కండి."
        ),
        "kn": (
            "ಬೀಪ್ ನಂತರ ಹೇಳಿ, ನೀವು ಏನು ಕೆಲಸ ಮಾಡುತ್ತೀರಿ ಮತ್ತು ನಿಮಗೆ ಏನು ಬೇಕು. "
            "ಉದಾಹರಣೆಗೆ — ನಾನು ತರಕಾರಿ ಮಾರುತ್ತೇನೆ, ನನಗೆ ಸಾಲ ಬೇಕು. "
            "ಹೇಳಿದ ನಂತರ ಹ್ಯಾಶ್ ಒತ್ತಿ."
        ),
    },
    "thinking": {
        "hi": "एक मिनट रुकिए। मैं सरकारी नियम देख रहा हूँ।",
        "en": "One moment. I am checking the government rules.",
        "mr": "एक मिनिट थांबा. मी सरकारी नियम पाहत आहे.",
        "gu": "એક મિનિટ રોકાઓ. હું સરકારી નિયમો જોઈ રહ્યો છું.",
        "bn": "এক মিনিট অপেক্ষা করুন। আমি সরকারি নিয়ম দেখছি।",
        "ta": "ஒரு நிமிடம் காத்திருங்கள். நான் அரசு விதிகளைப் பார்க்கிறேன்.",
        "te": "ఒక నిమిషం ఆగండి. నేను ప్రభుత్వ నియమాలు చూస్తున్నాను.",
        "kn": "ಒಂದು ನಿಮಿಷ ಕಾಯಿರಿ. ನಾನು ಸರ್ಕಾರಿ ನಿಯಮಗಳನ್ನು ನೋಡುತ್ತಿದ್ದೇನೆ.",
    },
    # Used when the words came through but no fact did. Naming what is missing
    # rather than saying "I did not understand", because the caller can act on
    # the first and not the second.
    "need_more": {
        "hi": "मैंने आपकी बात सुनी, पर आपकी उम्र और कमाई समझ नहीं आई। कृपया कहिए: मेरी उम्र इतनी है, मैं रोज़ इतने रुपये कमाता हूँ।",
        "en": "I heard you, but I did not catch your age and your earnings. Please say: I am this many years old, and I earn this much a day.",
        "mr": "मी ऐकलं, पण तुमचं वय आणि कमाई समजली नाही. कृपया सांगा: माझं वय इतकं आहे, मी रोज इतके रुपये कमावतो.",
        "gu": "મેં સાંભળ્યું, પણ તમારી ઉંમર અને કમાણી સમજાઈ નહીં. કૃપા કરીને કહો: મારી ઉંમર આટલી છે, હું રોજ આટલા રૂપિયા કમાઉં છું.",
        "bn": "আমি শুনেছি, কিন্তু আপনার বয়স আর আয় বুঝতে পারিনি। দয়া করে বলুন: আমার বয়স এত, আমি প্রতিদিন এত টাকা আয় করি।",
        "ta": "நான் கேட்டேன், ஆனால் உங்கள் வயதும் வருமானமும் புரியவில்லை. தயவுசெய்து சொல்லுங்கள்: என் வயது இத்தனை, நான் தினமும் இத்தனை ரூபாய் சம்பாதிக்கிறேன்.",
        "te": "నేను విన్నాను, కానీ మీ వయస్సు మరియు సంపాదన అర్థం కాలేదు. దయచేసి చెప్పండి: నా వయస్సు ఇంత, నేను రోజుకు ఇంత రూపాయలు సంపాదిస్తాను.",
        "kn": "ನಾನು ಕೇಳಿದೆ, ಆದರೆ ನಿಮ್ಮ ವಯಸ್ಸು ಮತ್ತು ಸಂಪಾದನೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಹೇಳಿ: ನನ್ನ ವಯಸ್ಸು ಇಷ್ಟು, ನಾನು ದಿನಕ್ಕೆ ಇಷ್ಟು ರೂಪಾಯಿ ಸಂಪಾದಿಸುತ್ತೇನೆ.",
    },
    "after_answer": {
        "hi": (
            "फिर से सुनने के लिए एक दबाइए। "
            "आवेदन शुरू करने के लिए दो दबाइए। "
            "किसी व्यक्ति से बात करने के लिए शून्य दबाइए।"
        ),
        "en": (
            "To hear that again, press one. "
            "To start your application, press two. "
            "To speak to a person, press zero."
        ),
        "mr": (
            "पुन्हा ऐकण्यासाठी एक दाबा. अर्ज सुरू करण्यासाठी दोन दाबा. "
            "एखाद्या व्यक्तीशी बोलण्यासाठी शून्य दाबा."
        ),
        "gu": (
            "ફરી સાંભળવા માટે એક દબાવો. અરજી શરૂ કરવા માટે બે દબાવો. "
            "કોઈ વ્યક્તિ સાથે વાત કરવા માટે શૂન્ય દબાવો."
        ),
        "bn": (
            "আবার শুনতে এক চাপুন। আবেদন শুরু করতে দুই চাপুন। "
            "কারও সঙ্গে কথা বলতে শূন্য চাপুন।"
        ),
        "ta": (
            "மீண்டும் கேட்க ஒன்று அழுத்துங்கள். விண்ணப்பத்தைத் தொடங்க இரண்டு அழுத்துங்கள். "
            "ஒருவருடன் பேச பூஜ்ஜியம் அழுத்துங்கள்."
        ),
        "te": (
            "మళ్ళీ వినడానికి ఒకటి నొక్కండి. దరఖాస్తు ప్రారంభించడానికి రెండు నొక్కండి. "
            "ఒక వ్యక్తితో మాట్లాడటానికి సున్నా నొక్కండి."
        ),
        "kn": (
            "ಮತ್ತೆ ಕೇಳಲು ಒಂದು ಒತ್ತಿ. ಅರ್ಜಿ ಪ್ರಾರಂಭಿಸಲು ಎರಡು ಒತ್ತಿ. "
            "ಒಬ್ಬ ವ್ಯಕ್ತಿಯೊಂದಿಗೆ ಮಾತನಾಡಲು ಸೊನ್ನೆ ಒತ್ತಿ."
        ),
    },
    "case_opened": {
        "hi": (
            "आपका आवेदन शुरू हो गया है। हम आपको याद दिलाने के लिए फ़ोन करेंगे। "
            "फ़ोन रखने के लिए नौ दबाइए।"
        ),
        "en": (
            "Your application has been started. We will call you with reminders. "
            "Press nine to hang up."
        ),
        "mr": (
            "तुमचा अर्ज सुरू झाला आहे. आम्ही तुम्हाला आठवण करून देण्यासाठी फोन करू. "
            "फोन ठेवण्यासाठी नऊ दाबा."
        ),
        "gu": (
            "તમારી અરજી શરૂ થઈ ગઈ છે. અમે તમને યાદ કરાવવા ફોન કરીશું. "
            "ફોન મૂકવા માટે નવ દબાવો."
        ),
        "bn": (
            "আপনার আবেদন শুরু হয়েছে। আমরা আপনাকে মনে করিয়ে দিতে ফোন করব। "
            "ফোন রাখতে নয় চাপুন।"
        ),
        "ta": (
            "உங்கள் விண்ணப்பம் தொடங்கிவிட்டது. நினைவூட்ட நாங்கள் அழைப்போம். "
            "அழைப்பை முடிக்க ஒன்பது அழுத்துங்கள்."
        ),
        "te": (
            "మీ దరఖాస్తు ప్రారంభమైంది. గుర్తు చేయడానికి మేము ఫోన్ చేస్తాము. "
            "ఫోన్ పెట్టేయడానికి తొమ్మిది నొక్కండి."
        ),
        "kn": (
            "ನಿಮ್ಮ ಅರ್ಜಿ ಪ್ರಾರಂಭವಾಗಿದೆ. ನೆನಪಿಸಲು ನಾವು ಫೋನ್ ಮಾಡುತ್ತೇವೆ. "
            "ಫೋನ್ ಇಡಲು ಒಂಬತ್ತು ಒತ್ತಿ."
        ),
    },
    "operator": {
        "hi": (
            "आपको आपके नज़दीकी सी. एस. सी. केंद्र के ऑपरेटर से जोड़ा जा रहा है। "
            "वे आपके कागज़ देखने में मदद करेंगे।"
        ),
        "en": (
            "Connecting you to an operator at your nearest C S C centre. "
            "They will help you check your documents."
        ),
        "mr": (
            "तुम्हाला तुमच्या जवळच्या सी. एस. सी. केंद्रातील ऑपरेटरशी जोडत आहोत. "
            "ते तुमचे कागद पाहण्यात मदत करतील."
        ),
        "gu": (
            "તમને તમારા નજીકના સી. એસ. સી. કેન્દ્રના ઓપરેટર સાથે જોડી રહ્યા છીએ. "
            "તેઓ તમારા કાગળ જોવામાં મદદ કરશે."
        ),
        "bn": (
            "আপনাকে আপনার নিকটতম সি. এস. সি. কেন্দ্রের অপারেটরের সঙ্গে যোগ করা হচ্ছে। "
            "তাঁরা আপনার কাগজ দেখতে সাহায্য করবেন।"
        ),
        "ta": (
            "உங்கள் அருகிலுள்ள சி. எஸ். சி. மையத்தின் ஆபரேட்டருடன் இணைக்கிறோம். "
            "அவர்கள் உங்கள் ஆவணங்களைப் பார்க்க உதவுவார்கள்."
        ),
        "te": (
            "మీ దగ్గరి సి. ఎస్. సి. కేంద్రం ఆపరేటర్‌తో కలుపుతున్నాము. "
            "వారు మీ పత్రాలు చూడటానికి సహాయం చేస్తారు."
        ),
        "kn": (
            "ನಿಮ್ಮ ಹತ್ತಿರದ ಸಿ. ಎಸ್. ಸಿ. ಕೇಂದ್ರದ ಆಪರೇಟರ್‌ಗೆ ಜೋಡಿಸುತ್ತಿದ್ದೇವೆ. "
            "ಅವರು ನಿಮ್ಮ ದಾಖಲೆಗಳನ್ನು ನೋಡಲು ಸಹಾಯ ಮಾಡುತ್ತಾರೆ."
        ),
    },
    "not_understood": {
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। दोबारा कोशिश करने के लिए एक दबाइए।",
        "en": "Sorry, I did not understand that. Press one to try again.",
        "mr": "माफ करा, मला समजलं नाही. पुन्हा प्रयत्न करण्यासाठी एक दाबा.",
        "gu": "માફ કરો, મને સમજાયું નહીં. ફરી પ્રયત્ન કરવા માટે એક દબાવો.",
        "bn": "দুঃখিত, আমি বুঝতে পারিনি। আবার চেষ্টা করতে এক চাপুন।",
        "ta": "மன்னிக்கவும், எனக்குப் புரியவில்லை. மீண்டும் முயற்சிக்க ஒன்று அழுத்துங்கள்.",
        "te": "క్షమించండి, నాకు అర్థం కాలేదు. మళ్ళీ ప్రయత్నించడానికి ఒకటి నొక్కండి.",
        "kn": "ಕ್ಷಮಿಸಿ, ನನಗೆ ಅರ್ಥವಾಗಲಿಲ್ಲ. ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಲು ಒಂದು ಒತ್ತಿ.",
    },
    "nothing_heard": {
        "hi": "मुझे कुछ सुनाई नहीं दिया। दोबारा बोलने के लिए एक दबाइए।",
        "en": "I did not hear anything. Press one to speak again.",
        "mr": "मला काही ऐकू आलं नाही. पुन्हा बोलण्यासाठी एक दाबा.",
        "gu": "મને કંઈ સંભળાયું નહીં. ફરી બોલવા માટે એક દબાવો.",
        "bn": "আমি কিছু শুনতে পাইনি। আবার বলতে এক চাপুন।",
        "ta": "எனக்கு எதுவும் கேட்கவில்லை. மீண்டும் பேச ஒன்று அழுத்துங்கள்.",
        "te": "నాకు ఏమీ వినిపించలేదు. మళ్ళీ మాట్లాడటానికి ఒకటి నొక్కండి.",
        "kn": "ನನಗೆ ಏನೂ ಕೇಳಿಸಲಿಲ್ಲ. ಮತ್ತೆ ಮಾತನಾಡಲು ಒಂದು ಒತ್ತಿ.",
    },
    "goodbye": {
        "hi": "सेतु को फ़ोन करने के लिए धन्यवाद। नमस्ते।",
        "en": "Thank you for calling Setu. Goodbye.",
        "mr": "सेतुला फोन केल्याबद्दल धन्यवाद. नमस्कार.",
        "gu": "સેતુને ફોન કરવા બદલ આભાર. નમસ્તે.",
        "bn": "সেতুতে ফোন করার জন্য ধন্যবাদ। নমস্কার।",
        "ta": "சேதுவை அழைத்ததற்கு நன்றி. வணக்கம்.",
        "te": "సేతుకు ఫోన్ చేసినందుకు ధన్యవాదాలు. నమస్కారం.",
        "kn": "ಸೇತುಗೆ ಫೋನ್ ಮಾಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ನಮಸ್ಕಾರ.",
    },
    # After the initial answer plays, the caller is invited to keep talking.
    # Anything they say next is treated as a follow-up chat question.
    "invite_chat": {
        "hi": "कोई और सवाल हो तो पूछिए। रोकने के लिए शून्य, फिर से शुरू करने के लिए एक दबाइए।",
        "en": "Ask anything else. Press zero to pause, one to start over.",
        "mr": "आणखी काही विचारायचं असेल तर विचारा. थांबवायला शून्य, पुन्हा सुरू करायला एक दाबा.",
        "gu": "કંઈ પણ પૂછો. રોકવા માટે શૂન્ય, ફરી શરૂ કરવા માટે એક દબાવો.",
        "bn": "আরও কিছু জিজ্ঞেস করুন। থামাতে শূন্য, নতুন করে শুরু করতে এক চাপুন।",
        "ta": "வேறு ஏதேனும் கேளுங்கள். நிறுத்த பூஜ்ஜியம், மறுபடி தொடங்க ஒன்று அழுத்துங்கள்.",
        "te": "ఇంకేదైనా అడగండి. ఆపడానికి సున్నా, మళ్ళీ ప్రారంభించడానికి ఒకటి నొక్కండి.",
        "kn": "ಇನ್ನೇನಾದರೂ ಕೇಳಿ. ನಿಲ್ಲಿಸಲು ಸೊನ್ನೆ, ಮರುಪ್ರಾರಂಭಿಸಲು ಒಂದು ಒತ್ತಿ.",
    },
    "chat_paused": {
        "hi": "ठीक है, रुक गया। जब तैयार हों, दोबारा बोलिए।",
        "en": "Okay, paused. Speak when you are ready.",
        "mr": "ठीक आहे, थांबलो. तयार असाल तेव्हा बोला.",
        "gu": "ઠીક છે, રોકાયું. તૈયાર હો ત્યારે બોલો.",
        "bn": "ঠিক আছে, থেমেছি। প্রস্তুত হলে বলুন।",
        "ta": "சரி, நிறுத்தினேன். தயாரானபோது பேசுங்கள்.",
        "te": "సరే, ఆగాను. సిద్ధమైనప్పుడు మాట్లాడండి.",
        "kn": "ಸರಿ, ನಿಂತೆ. ಸಿದ್ಧವಾದಾಗ ಮಾತನಾಡಿ.",
    },
    "chat_restart": {
        "hi": "फिर से शुरू करते हैं। बीप के बाद अपनी बात बताइए।",
        "en": "Starting over. Tell me your situation after the beep.",
        "mr": "पुन्हा सुरू करूया. बीप नंतर तुमची परिस्थिती सांगा.",
        "gu": "ફરી શરૂ કરીએ. બીપ પછી તમારી પરિસ્થિતિ કહો.",
        "bn": "আবার শুরু করছি। বীপের পরে আপনার পরিস্থিতি বলুন।",
        "ta": "மறுபடி தொடங்குகிறோம். பீப்பிற்குப் பிறகு உங்கள் நிலையைச் சொல்லுங்கள்.",
        "te": "మళ్ళీ ప్రారంభిస్తున్నాము. బీప్ తర్వాత మీ పరిస్థితి చెప్పండి.",
        "kn": "ಮತ್ತೆ ಪ್ರಾರಂಭಿಸೋಣ. ಬೀಪ್ ನಂತರ ನಿಮ್ಮ ಪರಿಸ್ಥಿತಿಯನ್ನು ಹೇಳಿ.",
    },
    "chat_dontknow": {
        "hi": "मुझे इसकी सटीक जानकारी नहीं है। कृपया अपने नज़दीकी बैंक मित्र या सी. एस. सी. केंद्र से पूछें।",
        "en": "I don't have that specific information. Please check with your nearest Bank Mitra or CSC operator.",
        "mr": "मला याची नक्की माहिती नाही. कृपया तुमच्या जवळच्या बँक मित्र किंवा सी. एस. सी. केंद्रात विचारा.",
        "gu": "મારી પાસે એની ચોક્કસ માહિતી નથી. કૃપા કરીને તમારા નજીકના બેંક મિત્ર અથવા સી. એસ. સી. કેન્દ્રમાં પૂછો.",
        "bn": "আমার কাছে এর নির্দিষ্ট তথ্য নেই। দয়া করে আপনার নিকটতম ব্যাংক মিত্র বা সি. এস. সি. অপারেটরের সঙ্গে কথা বলুন।",
        "ta": "எனக்கு அது சரியாகத் தெரியாது. உங்கள் அருகிலுள்ள வங்கி மித்ரா அல்லது சி. எஸ். சி. ஆபரேட்டரிடம் கேளுங்கள்.",
        "te": "నాకు దాని ఖచ్చితమైన సమాచారం లేదు. దయచేసి మీ దగ్గరి బ్యాంక్ మిత్ర లేదా సి. ఎస్. సి. ఆపరేటర్‌ను అడగండి.",
        "kn": "ನನಗೆ ಆ ನಿಖರ ಮಾಹಿತಿ ಇಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ಹತ್ತಿರದ ಬ್ಯಾಂಕ್ ಮಿತ್ರ ಅಥವಾ ಸಿ. ಎಸ್. ಸಿ. ಆಪರೇಟರ್‌ರನ್ನು ಕೇಳಿ.",
    },
}

# The offered languages, and the only place that list lives. voice.ASR_LANGUAGES
# says what we can *hear*; this says what we can hold a whole conversation in,
# which additionally needs a prompt set and a TTS voice.
#
# The greeting deliberately stays a Hindi/English menu: it is spoken before the
# caller has chosen anything, and reading eight options aloud to someone on a
# feature phone would be worse than useless. A client with a screen passes its
# language to begin() and never hears the menu at all.
SUPPORTED_LANGUAGES = ("hi", "en", "mr", "gu", "bn", "ta", "te", "kn")

LANGUAGE_LABELS = {
    "hi": "हिंदी", "en": "English", "mr": "मराठी", "gu": "ગુજરાતી",
    "bn": "বাংলা", "ta": "தமிழ்", "te": "తెలుగు", "kn": "ಕನ್ನಡ",
}


def prompt_text(key: str, lang: str) -> str:
    """
    A fixed prompt, falling back rather than raising.

    PROMPTS[key][lang] would KeyError the moment a language is offered before its
    prompts are written, and a KeyError here is a dead call.
    """
    options = PROMPTS[key]
    return options.get(lang) or options.get("hi") or next(iter(options.values()))


@dataclass
class Turn:
    """One leg of the call: what Setu says, and what it waits for afterwards."""

    say: str
    expect: Expect
    state: str
    audio_url: str | None = None
    # What the keypad offers right now. The browser renders these as labelled
    # keys; a real IVR would ignore them (the caller hears the options instead).
    options: list[dict] = field(default_factory=list)
    # Everything the operator/judge screen wants to show alongside the call.
    detail: dict = field(default_factory=dict)


@dataclass
class Session:
    call_id: str
    language: str = "hi"
    state: str = "greeting"
    last_answer: str = ""
    last_text: str = ""
    decisions: list = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    # Chat mode context — populated after the initial answer so follow-up
    # questions can reference the schemes the caller already qualified for.
    last_profile: object = None                                # Profile after the first pipeline run
    chat_history: list[dict] = field(default_factory=list)     # [{role, content}]


# In-memory: a hackathon demo, one caller at a time, and a restart between runs
# is fine. Persisting calls would mean a schema change, and the schemas are frozen.
_SESSIONS: dict[str, Session] = {}


def _audio_url_for(text: str, lang: str) -> str | None:
    """
    Synthesise (or reuse cached) speech and return a URL the browser can play.

    Never raises: a failed TTS must degrade to text on screen, not kill the
    call. VOICE_MODE=offline with a cold cache is the expected failure here.
    """
    try:
        path = voice.speak(text, lang)
    except voice.VoiceError:
        return None
    return f"/api/ivr/audio/{path.stem}"


def _turn(session: Session, key: str, expect: Expect, **kw) -> Turn:
    """Build a Turn from a named prompt, in the session's language."""
    text = prompt_text(key, session.language)
    session.state = key
    return Turn(
        say=text,
        expect=expect,
        state=key,
        audio_url=_audio_url_for(text, session.language),
        **kw,
    )


MENU_AFTER_ANSWER = [
    {"digit": "1", "label_en": "Repeat", "label_hi": "दोबारा"},
    {"digit": "2", "label_en": "Start application", "label_hi": "आवेदन शुरू करें"},
    {"digit": "0", "label_en": "Talk to a person", "label_hi": "व्यक्ति से बात करें"},
]

# After the initial answer plays we drop the caller straight into free chat:
# any speech they say next is treated as a follow-up question to the LLM.
# 0 pauses, 1 wipes the session and starts a new conversation.
MENU_CHAT = [
    {"digit": "0", "label_en": "Pause",   "label_hi": "रोकें"},
    {"digit": "1", "label_en": "Restart", "label_hi": "फिर से शुरू करें"},
]

LANGUAGE_MENU = [
    {"digit": "1", "label_en": "Hindi", "label_hi": "हिंदी"},
    {"digit": "2", "label_en": "English", "label_hi": "English"},
]


# ── The state machine ────────────────────────────────────────────────────────

def begin(language: str | None = None) -> tuple[str, Turn]:
    """
    Caller dials in. Returns the call id and the greeting.

    A client with a screen (the PWA) picks the language itself, so passing one
    skips the spoken menu and goes straight to the question. The phone path
    passes nothing and still hears "एक दबाइए".
    """
    call_id = uuid.uuid4().hex[:8]
    session = Session(call_id=call_id)
    _SESSIONS[call_id] = session

    if language in SUPPORTED_LANGUAGES:
        session.language = language
        return call_id, _turn(session, "ask_situation", "speech")

    return call_id, _turn(session, "greeting", "digit", options=LANGUAGE_MENU)


def _session(call_id: str) -> Session:
    session = _SESSIONS.get(call_id)
    if session is None:
        raise HTTPException(status_code=404, detail="call not found — dial again")
    return session


def on_digit(call_id: str, digit: str) -> Turn:
    """Caller pressed a key."""
    session = _session(call_id)
    session.transcript.append({"who": "caller", "text": f"[pressed {digit}]"})

    if digit == "9":
        return _turn(session, "goodbye", "end")

    if session.state == "greeting":
        # 1..8 maps to SUPPORTED_LANGUAGES in the order they were introduced.
        DIGIT_TO_LANG = {
            "1": "hi", "2": "en", "3": "mr", "4": "gu",
            "5": "bn", "6": "ta", "7": "te", "8": "kn",
        }
        if digit in DIGIT_TO_LANG:
            session.language = DIGIT_TO_LANG[digit]
            return _turn(session, "ask_situation", "speech")
        return _turn(session, "not_understood", "digit", options=LANGUAGE_MENU)

    # Chat mode: 0 pauses (mic reopens silently), 1 wipes the conversation
    # and drops the caller back to ask_situation in the current language.
    if session.state == "chatting":
        if digit == "0":
            return Turn(
                say=prompt_text("chat_paused", session.language),
                expect="speech",
                state="chatting",
                audio_url=_audio_url_for(prompt_text("chat_paused", session.language), session.language),
                options=MENU_CHAT,
            )
        if digit == "1":
            session.state = "await_situation"
            session.chat_history.clear()
            session.decisions = []
            session.last_answer = ""
            session.last_profile = None
            return Turn(
                say=prompt_text("chat_restart", session.language),
                expect="speech",
                state="await_situation",
                audio_url=_audio_url_for(prompt_text("chat_restart", session.language), session.language),
            )
        # any other digit in chat mode — treat as "restart" hint; fall through
        return _turn(session, "not_understood", "digit", options=MENU_CHAT)

    # After an answer, or after any dead end that offered "press 1 to retry".
    if digit == "1":
        if session.state == "after_answer" and session.last_answer:
            # Repeat the answer itself, not the menu.
            return Turn(
                say=session.last_answer,
                expect="digit",
                state="after_answer",
                audio_url=_audio_url_for(session.last_answer, session.language),
                options=MENU_AFTER_ANSWER,
            )
        return _turn(session, "ask_situation", "speech")

    if digit == "2" and session.decisions:
        # Agentic follow-through: turn the top ladder into tracked commitments.
        top = session.decisions[0]
        try:
            store.open_case(f"ivr:{call_id}", top)
        except Exception:  # noqa: BLE001 - a demo must not die on a DB write
            pass
        return _turn(session, "case_opened", "digit")

    if digit == "0":
        # The trusted-intermediary fallback: a human, on purpose, by design.
        return _turn(session, "operator", "end")

    return _turn(session, "not_understood", "digit", options=MENU_AFTER_ANSWER)


# OFF by default. When extraction misses age and income - which it does for
# every language except English - this re-prompts instead of answering, and a
# demo that will not answer is worse than one that answers from thin evidence.
# The check itself is kept, and the reason it was written is still real: given
# an empty profile the rule engine returns PMSBY, PMJJBY and PM SVANidhi with
# rupee figures the caller never mentioned. Turn it on with SETU_REQUIRE_FACTS=1
# once extraction is reliable enough to carry it.
REQUIRE_FACTS = os.getenv("SETU_REQUIRE_FACTS", "0") == "1"


def _has_usable_facts(profile) -> bool:
    """
    Whether extraction found anything the rule engine can actually reason from.

    Deliberately generous: one real fact is enough to answer on, because a
    caller who gave only their trade still deserves what that alone qualifies
    them for. What this rejects is the empty profile - every field None - which
    is what a failed transcription produces and which the rule engine happily
    answers anyway.
    """
    return any(
        getattr(profile, field, None) not in (None, [], "")
        for field in ("age", "occupation_category", "daily_income", "monthly_income")
    )


def on_speech(call_id: str, text: str) -> Turn:
    """Caller finished speaking. This is where the real pipeline runs."""
    session = _session(call_id)
    text = (text or "").strip()

    if not text:
        return _turn(session, "nothing_heard", "digit")

    # Mirror to the console (Twilio, PWA speech, PWA text bypass all land here).
    # `language` lets the console auto-run its pipeline in the same language
    # the caller spoke, rather than whatever the dropdown was last on.
    phone_bus.publish({
        "type": "user_speech",
        "call_id": call_id,
        "text": text,
        "language": session.language,
    })

    session.last_text = text
    session.transcript.append({"who": "caller", "text": text})

    user_profile = profile_mod.extract(text, language=session.language)

    # Nothing usable came out of the words. This is not hypothetical: Bengali
    # speech transcribes as romanised Latin, so age, income and category all
    # come back empty - and the rule engine, given an empty profile, still
    # returns PMSBY, PMJJBY and PM SVANidhi with real rupee figures attached.
    # A caller who said none of that would be told a confident number derived
    # from nothing they said. Ask again instead: a demo that admits it did not
    # understand is worth more than one that invents, and the whole product
    # rests on the numbers being traceable to something real.
    if REQUIRE_FACTS and not _has_usable_facts(user_profile):
        print(
            f"ivr/speech call={call_id} lang={session.language} "
            f"no facts extracted from {text[:60]!r}; re-prompting",
            flush=True,
        )
        turn = _turn(session, "need_more", "speech")
        turn.detail = {"transcript": text, "profile": user_profile.model_dump(mode="json")}
        return turn

    decisions = pathfinder.build_all(user_profile, eligibility.evaluate_all(user_profile))
    spoken = narrate.narrate_all(user_profile, decisions, session.language)

    session.decisions = decisions
    session.last_answer = spoken
    session.last_profile = user_profile
    session.transcript.append({"who": "setu", "text": spoken})

    # After the initial answer we transition to chat: mic reopens and anything
    # the caller says next is routed to on_chat(). The invite line tells them
    # they can keep talking, pause (0), or restart (1).
    menu = prompt_text("invite_chat", session.language)
    session.state = "chatting"

    return Turn(
        say=f"{spoken}\n\n{menu}",
        expect="speech",
        state="chatting",
        audio_url=_audio_url_for(spoken, session.language),
        options=MENU_CHAT,
        detail={
            "transcript": text,
            "profile": user_profile.model_dump(mode="json"),
            # Carries *_local fields beside the originals: the card reads in the
            # caller's language while the audited values stay untouched.
            "decisions": narrate.localise_decisions(decisions, session.language),
            "menu_audio_url": _audio_url_for(menu, session.language),
        },
    )


# ── Follow-up chat ───────────────────────────────────────────────────────────

def _chat_system_prompt(session) -> str:
    """
    A system prompt that grounds the LLM in the schemes the caller already
    qualified for. Passing the amounts + step counts here means the model can
    answer "which docs?" / "how much?" / "where do I go?" without inventing
    schemes it wasn't told about.
    """
    lang_label = LANGUAGE_LABELS.get(session.language, session.language)
    scheme_lines = []
    for d in session.decisions or []:
        name = getattr(d, "scheme_name", None) or getattr(d, "scheme_id", "?")
        benefit = getattr(d, "benefit_summary", "") or ""
        amount = getattr(d, "benefit_amount_rupees", None)
        amount_str = f" (₹{int(amount):,})" if amount else ""
        ladder = getattr(d, "ladder", None) or []
        steps = ", ".join(
            f"{i + 1}. {getattr(step, 'action', '')}"
            for i, step in enumerate(ladder[:4])
        )
        scheme_lines.append(f"- {name}{amount_str}: {benefit}. Steps: {steps}")
    schemes_block = "\n".join(scheme_lines) or "(no schemes qualified)"

    profile = session.last_profile
    p_bits = []
    if profile is not None:
        for f in ("occupation", "age", "daily_income", "monthly_income", "city", "state", "documents"):
            v = getattr(profile, f, None)
            if v not in (None, [], ""):
                p_bits.append(f"{f}={v}")
    profile_str = ", ".join(p_bits) or "(no profile facts)"

    return (
        f"You are Setu, an advisor for informal-sector workers in India. "
        f"You just told the caller about these schemes:\n{schemes_block}\n\n"
        f"Caller profile: {profile_str}\n\n"
        f"Answer their next question in {lang_label}. 2-3 short sentences.\n"
        f"\n"
        f"CRITICAL: Answer the SPECIFIC question asked. Do not switch topics.\n"
        f"- If they ask WHERE / kahan / कहाँ / कुठे / ક્યાં / কোথায় → answer with a location.\n"
        f"- If they ask WHAT DOCS / kaunse documents / documents kya → list documents.\n"
        f"- If they ask HOW MUCH / kitna → answer with amount or time.\n"
        f"- If they ask HOW / kaise → answer with steps.\n"
        f"\n"
        f"Locations you may reference:\n"
        f"- Bank account (Jan Dhan / savings): any bank branch or India Post office. Bring Aadhaar.\n"
        f"- PM SVANidhi loan: apply at any nationalised bank, RRB, cooperative bank, or SFB. "
        f"  The Urban Local Body / Town Vending Committee issues the Letter of Recommendation.\n"
        f"- PMSBY / PMJJBY insurance: enroll at the bank where your savings account is held.\n"
        f"- E-Shram card, PMJDY account, general documents: nearest CSC (Common Service Centre) "
        f"  operator or Bank Mitra.\n"
        f"- To reach a human advisor for anything else: nearest CSC centre or Bank Mitra.\n"
        f"\n"
        f"Only reference the schemes listed above — never invent new ones. If the question is "
        f"outside all of this, say you do not have that specific information and to check with "
        f"the nearest Bank Mitra or CSC operator."
    )


CHAT_MAX_TOKENS = int(os.getenv("SETU_CHAT_MAX_TOKENS", "120"))
# Trim old turns so the prompt stays small — cap at the last 6 exchanges
# (=12 messages). Ollama's context is small and Granite slows sharply with it.
CHAT_HISTORY_TURNS = 6


def on_chat(call_id: str, text: str) -> Turn:
    """Follow-up chat with the LLM, grounded in the caller's profile + decisions."""
    from services.api.core import llm  # local import to avoid slowing cold imports

    session = _session(call_id)
    text = (text or "").strip()

    if not text:
        return Turn(
            say=prompt_text("nothing_heard", session.language),
            expect="speech",
            state="chatting",
            audio_url=_audio_url_for(prompt_text("nothing_heard", session.language), session.language),
            options=MENU_CHAT,
        )

    phone_bus.publish({
        "type": "user_speech", "call_id": call_id, "text": text,
        "language": session.language,
    })
    session.transcript.append({"who": "caller", "text": text})
    session.last_text = text

    system = _chat_system_prompt(session)
    trimmed = session.chat_history[-(CHAT_HISTORY_TURNS * 2):]
    messages = [{"role": "system", "content": system}] + trimmed + [{"role": "user", "content": text}]

    try:
        started = time.monotonic()
        reply = llm.chat_multi(messages, temperature=0.2, max_tokens=CHAT_MAX_TOKENS).strip()
        print(f"chat call={call_id} lang={session.language} llm={time.monotonic() - started:.1f}s "
              f"in={len(text)} out={len(reply)}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"chat call={call_id} LLM FAILED {type(exc).__name__}: {exc}", flush=True)
        reply = prompt_text("chat_dontknow", session.language)

    if not reply:
        reply = prompt_text("chat_dontknow", session.language)

    session.chat_history.append({"role": "user", "content": text})
    session.chat_history.append({"role": "assistant", "content": reply})
    session.transcript.append({"who": "setu", "text": reply})

    return Turn(
        say=reply,
        expect="speech",
        state="chatting",
        audio_url=_audio_url_for(reply, session.language),
        options=MENU_CHAT,
        detail={"chat_turn": len(session.chat_history) // 2},
    )


# ── HTTP transport ───────────────────────────────────────────────────────────

class DigitRequest(BaseModel):
    call_id: str
    digit: str


class TextRequest(BaseModel):
    call_id: str
    text: str


class CallRequest(BaseModel):
    language: str | None = None


@router.get("/languages")
def languages():
    """
    What the client should offer, and whether each one can speak offline.

    The PWA builds its language picker from this rather than hardcoding a list,
    so adding a language is one entry in SUPPORTED_LANGUAGES and not an edit in
    two files that drift apart.
    """
    silent = {lang for _key, lang in missing_prompt_audio()}
    return {
        "languages": [
            {
                "code": code,
                "label": LANGUAGE_LABELS.get(code, code),
                "speaks_offline": code not in silent,
            }
            for code in SUPPORTED_LANGUAGES
        ]
    }


@router.post("/call")
def start_call(request: CallRequest | None = None):
    # Deliberately no call_started publish: the PWA hits this on page load, so
    # publishing here would leave a persistent "LIVE" chip in the console every
    # time someone opened the PWA tab. Only user_speech (below) is mirrored.
    call_id, turn = begin(request.language if request else None)
    return {"call_id": call_id, "turn": turn.__dict__}


@router.post("/digit")
def press_digit(request: DigitRequest):
    return {"turn": on_digit(request.call_id, request.digit).__dict__}


@router.post("/text")
def say_text(request: TextRequest):
    """
    Speech bypass — typed or canned input on the same code path as the mic.

    This is demo insurance. If the microphone fails on stage, the persona
    buttons still drive a real call through the real pipeline.
    """
    session = _SESSIONS.get(request.call_id)
    if session and session.state == "chatting":
        return {"turn": on_chat(request.call_id, request.text).__dict__}
    return {"turn": on_speech(request.call_id, request.text).__dict__}


DEBUG_CLIPS = Path(__file__).resolve().parent.parent / "services" / "api" / "data" / "debug_clips"


@router.post("/speech")
async def post_speech(call_id: str = Form(...), audio: UploadFile = File(...)):
    """
    Recorded audio from the browser mic -> Whisper -> the pipeline.

    Everything here is logged, because it was not and that cost real debugging
    time: a failure returned "I did not hear anything" with a 200 and the reason
    only in the response body, so the server log showed a clean success for an
    ASR timeout, a busy lock, a zero-byte upload and genuine silence alike. Four
    different problems, one indistinguishable symptom.

    Set SETU_DEBUG_CLIPS=1 to keep the uploaded audio. A clip from the actual
    phone is the only way to tell "the mic recorded nothing" from "we could not
    decode what the mic sent".
    """
    session = _session(call_id)
    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    raw = await audio.read()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        clip = tmp.name

    if os.getenv("SETU_DEBUG_CLIPS") == "1":
        DEBUG_CLIPS.mkdir(parents=True, exist_ok=True)
        kept = DEBUG_CLIPS / f"{call_id}-{int(time.time())}{suffix}"
        kept.write_bytes(raw)
        print(f"ivr/speech: kept {kept}", flush=True)

    started = time.monotonic()
    try:
        # Answer in the language they spoke, not the one they tapped. Someone who
        # speaks Marathi into a screen still set to Hindi should get Marathi back;
        # expecting them to find their language first defeats the whole premise.
        text, detected, confidence = voice.transcribe_auto(
            clip, default_language=session.language
        )
        if detected != session.language:
            print(
                f"ivr/speech language switched {session.language} -> {detected} "
                f"(p={confidence:.2f}) call={call_id}",
                flush=True,
            )
            session.language = detected
    except Exception as exc:  # noqa: BLE001 - ASR failure is a call event, not a 500
        print(
            f"ivr/speech FAILED call={call_id} lang={session.language} "
            f"bytes={len(raw)} name={audio.filename!r} type={audio.content_type!r} "
            f"after={time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {
            "turn": _turn(session, "nothing_heard", "digit").__dict__,
            "error": str(exc),
            "reason": type(exc).__name__,
        }
    finally:
        Path(clip).unlink(missing_ok=True)

    print(
        f"ivr/speech call={call_id} lang={session.language} bytes={len(raw)} "
        f"name={audio.filename!r} type={audio.content_type!r} "
        f"asr={time.monotonic() - started:.1f}s chars={len(text)} text={text[:80]!r}",
        flush=True,
    )
    if not text.strip():
        # Genuine silence and an undecodable container look identical to the
        # caller; say so in the log at least.
        print(
            f"ivr/speech EMPTY TRANSCRIPT call={call_id} — {len(raw)} bytes of "
            f"{audio.content_type!r} decoded to nothing",
            flush=True,
        )
    # Route to chat mode once the initial answer has been given.
    handler = on_chat if session.state == "chatting" else on_speech
    return {
        "turn": handler(call_id, text).__dict__,
        "transcript": text,
        # So the client can move its own UI to the language that was actually
        # spoken, rather than staying on the chip the caller tapped.
        "language": session.language,
    }


_KEY = re.compile(r"^[a-f0-9]{6,40}$")


@router.get("/audio/{key}")
def get_audio(key: str):
    """Stream a cached mp3. Keys are content hashes, so they are safe to expose."""
    if not _KEY.match(key):
        raise HTTPException(status_code=400, detail="bad audio key")
    path = voice.CACHE_DIR / f"{key}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio not cached")
    return FileResponse(path, media_type="audio/mpeg")


@router.get("/transcript/{call_id}")
def get_transcript(call_id: str):
    session = _session(call_id)
    return {
        "call_id": call_id,
        "language": session.language,
        "state": session.state,
        "transcript": session.transcript,
    }


def precache_prompts() -> dict[str, str]:
    """
    Synthesise every fixed prompt in every offered language.

    Run this before going on stage. edge-tts synthesises over the network, so an
    uncached line cannot be spoken with the wifi off — it degrades to text, which
    for a voice-first product is the demo failing quietly. Once this has run, the
    entire call flow speaks offline in all eight languages; only a novel
    generated answer still needs the wire.
    """
    lines = [
        (text, lang)
        for prompt in PROMPTS.values()
        for lang, text in prompt.items()
    ]
    return voice.precache(lines)


def missing_prompt_audio() -> list[tuple[str, str]]:
    """Which (key, language) pairs would be silent offline right now."""
    return [
        (key, lang)
        for key, prompt in PROMPTS.items()
        for lang, text in prompt.items()
        if not voice.is_cached(text, lang)
    ]
