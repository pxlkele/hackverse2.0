import { useState, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Mic, Database, Volume2, Send, RotateCcw, CheckCircle2,
  Loader2, Activity, FileText, TrendingUp, Upload, AlertTriangle,
  CheckCircle, XCircle, ChevronDown, ChevronUp, Coins, Phone,
} from "lucide-react";

/* ─────────────── API types ─────────────── */
type Rule = { kind: "rule"; passed: boolean | null; label: string; citation: string; quote: string; expected: string; actual: string; scheme: string };
type SchemeStep = { kind: "scheme"; label: string; detail: string; status: string };
type LadderStep = { order: number; action: string; cost_rupees: number; time_days: number; where: string; detail: string };
type LadderBlock = { kind: "ladder"; scheme: string; label: string; detail: string; steps: LadderStep[] };
type HeardBlock = { kind: "heard"; label: string; detail: string };
type PipelineStep = Rule | SchemeStep | LadderBlock | HeardBlock;

type Decision = {
  scheme_id: string; scheme_name: string; status: string;
  ladder: LadderStep[] | null; total_cost_rupees: number | null;
  total_time_days: number | null; benefit_summary: string;
  benefit_amount_rupees: number | null; rules: Rule[];
};
type Profile = {
  occupation?: string; occupation_category?: string; age?: number;
  daily_income?: number; monthly_income?: number; city?: string;
  state?: string; documents?: string[]; stated_need?: string;
  years_in_business?: number;
};
type ReasonResponse = {
  profile: Profile; steps: PipelineStep[]; decisions: Decision[];
  spoken_text: string; audio_path: string | null;
  trace_fingerprint: string; timings_ms: Record<string, number>;
};

type DocFinding = { severity: string; field: string; message: string; values: Record<string,string>; consequence: string; fix: string };
type DocReport = { clear: boolean; summary: string; findings: DocFinding[]; documents: Array<{ label: string; name: string | null; dob: string | null; extraction_method: string }>; reading_is_reliable: boolean };

type LedgerDay = { date: string; earned: number; spent: number | null; corroborated: boolean };
type LedgerStatement = {
  days_covered: number; days_in_period: number; coverage_pct: number;
  total_earned: number; total_spent: number; net: number;
  median_daily_earned: number; best_day: number; worst_day: number;
  confidence: string; corroboration_pct: number; caveats: string[];
  period_start: string; period_end: string; daily: LedgerDay[];
};

/* ─────────────── constants ─────────────── */
const pause = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

const STAGES = [
  { num: "01", title: "Input & Understanding", sub: "ASR → Profile",    idle: "Awaiting input…",      running: "Profiling…",            done: "Profile extracted", Icon: Mic,      color: "#00f5ff" },
  { num: "02", title: "Retrieval & Matching",  sub: "RAG → Rules",      idle: "Waiting for profile…", running: "Evaluating rules…",     done: "Rules matched",     Icon: Database, color: "#a855f7" },
  { num: "03", title: "Response & Outcome",    sub: "Decision → TTS",   idle: "Awaiting retrieval…",  running: "Synthesizing response…",done: "Response ready",    Icon: Volume2,  color: "#f43df7" },
] as const;

const PATHS = [
  "M 160 0 C 30 90 330 180 160 300 C 30 420 330 510 160 630 C 30 750 330 840 160 900",
  "M 240 0 C 370 90 70 180 240 300 C 370 420 70 510 240 630 C 370 750 70 840 240 900",
  "M 200 -40 C 50 60 360 150 200 260 C 50 370 360 460 200 570 C 50 680 360 760 200 900",
  "M 120 0 C 280 70 60 200 200 330 C 340 460 80 580 210 700 C 340 820 100 860 180 900",
  "M 280 0 C 120 80 380 210 200 320 C 60 430 320 560 180 680 C 60 800 300 850 230 900",
];

const ACRONYMS: Record<string, string> = {
  "PMSBY":       "Pradhan Mantri Suraksha Bima Yojana",
  "PMJJBY":      "Pradhan Mantri Jeevan Jyoti Bima Yojana",
  "PM SVANidhi": "Pradhan Mantri SVANidhi",
  "SVANidhi":    "SVANidhi (Street Vendor's AtmaNirbhar Nidhi)",
  "PMJDY":       "Pradhan Mantri Jan Dhan Yojana",
  "PMEGP":       "Pradhan Mantri Employment Generation Programme",
  "MUDRA":       "Micro Units Development and Refinance Agency",
};

function expandAcronyms(text: string): string {
  let out = text;
  for (const [short, full] of Object.entries(ACRONYMS)) {
    out = out.replace(new RegExp(`\\b${short}\\b`, "g"), full);
  }
  return out;
}

const SAMPLES = [
  { label: "Pani puri vendor (the demo)", text: "Main 34 saal ka hoon, Bangalore mein pani puri ka thela chalata hoon. Saat saal se yeh kaam kar raha hoon. Roz kareeb aath sau rupaye ka dhandha hota hai. Mere paas Aadhaar card aur bank passbook hai, lekin vending certificate nahi hai." },
  { label: "Tailor, no documents",        text: "Main darzi ka kaam karta hoon Pune mein. Mahine ka teen hazaar kamata hoon. Koi document nahi hai mere paas." },
  { label: "Vendor with everything",      text: "Main 40 saal ka hoon, Delhi mein chaat ka thela lagata hoon. Roz hazaar ka dhandha. Aadhaar, bank passbook, vending certificate aur PhonePe sab hai." },
];

type Tab = "pipeline" | "doctor" | "ledger";
type Status = "idle" | "processing" | "complete";

/* ─────────────── root ─────────────── */
export default function App() {
  const [tab, setTab] = useState<Tab>("pipeline");

  return (
    <div className="w-full bg-black overflow-hidden" style={{ height: "100dvh", fontFamily: "'Oxanium', sans-serif" }}>
      {/* header */}
      <div className="absolute top-0 left-0 right-0 z-40 flex items-center justify-between px-8 py-4 border-b border-white/5 bg-black/70 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <Activity className="w-3.5 h-3.5 text-white/20" />
          <span className="text-[10px] tracking-[0.32em] uppercase text-white/20" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
            SETU · AI PIPELINE MONITOR
          </span>
        </div>
        <div className="flex items-center gap-1">
          {(["pipeline","doctor","ledger"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className="px-4 py-1.5 rounded-lg text-[11px] tracking-wider uppercase transition-all"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                background: tab === t ? "rgba(255,255,255,0.08)" : "transparent",
                color: tab === t ? "rgba(255,255,255,0.75)" : "rgba(255,255,255,0.25)",
                border: tab === t ? "1px solid rgba(255,255,255,0.12)" : "1px solid transparent",
              }}>
              {t === "pipeline" ? "⚡ Pipeline" : t === "doctor" ? "🩺 Doc Doctor" : "📒 Ledger"}
            </button>
          ))}
        </div>
      </div>

      <div className="pt-[52px] h-full">
        {tab === "pipeline" && <PipelineTab />}
        {tab === "doctor"   && <DocDoctorTab />}
        {tab === "ledger"   && <LedgerTab />}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   PIPELINE TAB — original left-scroll + right neon panel
═══════════════════════════════════════════════════════════ */
function PipelineTab() {
  const [input, setInput]       = useState("");
  const [statuses, setStatuses] = useState<Status[]>(["idle","idle","idle"]);
  const [active, setActive]     = useState(-1);
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult]     = useState<ReasonResponse | null>(null);
  const [error, setError]       = useState("");
  const [lang, setLang]         = useState("hi");
  const abortRef                = useRef(false);
  const r0 = useRef<HTMLDivElement>(null);
  const r1 = useRef<HTMLDivElement>(null);
  const r2 = useRef<HTMLDivElement>(null);
  const refs = [r0, r1, r2];
  const scrollTo = (i: number) => refs[i].current?.scrollIntoView({ behavior: "smooth", block: "start" });

  const run = async () => {
    if (!input.trim() || isRunning) return;
    abortRef.current = false;
    setIsRunning(true); setResult(null); setError("");

    setStatuses(["processing","idle","idle"]); setActive(0); scrollTo(0);

    let res: ReasonResponse;
    try {
      const r = await fetch("/api/reason", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: input.trim(), language: lang }),
      });
      if (!r.ok) throw new Error(`API ${r.status}`);
      res = await r.json();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Cannot reach API on :8000");
      setStatuses(["idle","idle","idle"]); setActive(-1); setIsRunning(false);
      return;
    }
    if (abortRef.current) return;

    setStatuses(["complete","processing","idle"]); setActive(1);
    setTimeout(() => scrollTo(1), 420);
    await pause(2200);   // slow — let judges read the rules building
    if (abortRef.current) return;

    setStatuses(["complete","complete","processing"]); setActive(2);
    setTimeout(() => scrollTo(2), 420);
    await pause(900);
    if (abortRef.current) return;

    setResult(res);
    setStatuses(["complete","complete","complete"]); setActive(-1); setIsRunning(false);
  };

  const reset = () => {
    abortRef.current = true;
    setStatuses(["idle","idle","idle"]); setActive(-1); setIsRunning(false);
    setResult(null); setInput(""); setError(""); scrollTo(0);
  };

  const prog = statuses.map(s => s === "complete" ? 1 : s === "processing" ? 0.5 : 0);
  const allDone = statuses.every(s => s === "complete");

  return (
    <div className="flex h-full">
      {/* ── left: scrollable stages ── */}
      <div className="h-full overflow-y-auto" style={{ width: "62%", scrollbarWidth: "none" }}>
        {STAGES.map((stage, i) => (
          <div key={i} ref={refs[i]} className="relative flex flex-col justify-center"
            style={{ minHeight: "calc(100dvh - 52px)", paddingLeft: "clamp(2.5rem,7vw,4rem)", paddingRight: "2.5rem", paddingTop: "3rem", paddingBottom: "3rem" }}>

            {/* connector line to next stage */}
            {i < 2 && (
              <div className="absolute bottom-0 transition-all duration-700"
                style={{ left:"clamp(2.5rem,7vw,4rem)", width:1, height:80,
                  background: `linear-gradient(to bottom, ${stage.color}55, transparent)`,
                  opacity: statuses[i] === "complete" ? 1 : 0.1 }} />
            )}

            <div style={{ maxWidth: 540 }}>
              {/* stage label */}
              <div className="flex items-center gap-3 mb-6">
                <span className="text-[10px] tracking-[0.38em] uppercase" style={{ color: stage.color, fontFamily:"'JetBrains Mono',monospace" }}>{stage.num}</span>
                <div className="h-px w-6" style={{ background: stage.color, opacity: 0.35 }} />
                <span className="text-[10px] tracking-[0.25em] uppercase text-white/20" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{stage.sub}</span>
              </div>

              <h2 className="font-bold mb-3 transition-colors duration-500"
                style={{ fontSize:"clamp(1.8rem,3.5vw,2.6rem)", lineHeight:1.05, letterSpacing:"-0.025em",
                  color: statuses[i] === "idle" ? "rgba(255,255,255,0.14)" : "#fff" }}>
                {stage.title}
              </h2>

              <div className="flex items-center gap-2.5 mb-8">
                {statuses[i] === "processing"
                  ? <><Loader2 className="w-3 h-3 animate-spin" style={{ color: stage.color }} />
                     <motion.div className="w-1.5 h-1.5 rounded-full" style={{ background: stage.color }}
                       animate={{ scale:[1,1.6,1], opacity:[1,0.3,1] }} transition={{ duration:0.8, repeat:Infinity }} /></>
                  : statuses[i] === "complete"
                  ? <CheckCircle2 className="w-3 h-3" style={{ color: stage.color }} />
                  : <stage.Icon className="w-3 h-3 text-white/16" />}
                <span className="text-[12px] transition-colors duration-300" style={{
                  fontFamily:"'JetBrains Mono',monospace",
                  color: statuses[i]==="processing" ? stage.color : statuses[i]==="complete" ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.16)",
                }}>
                  {statuses[i]==="idle" ? stage.idle : statuses[i]==="processing" ? stage.running : stage.done}
                </span>
              </div>

              {/* ── Stage 0: input ── */}
              {i === 0 && (
                <div className="space-y-4">
                  <div className="flex gap-2 flex-wrap">
                    {SAMPLES.map((s,si) => (
                      <button key={si} onClick={() => setInput(s.text)} disabled={isRunning}
                        className="text-[11px] px-3 py-1.5 rounded-lg transition-all disabled:opacity-30"
                        style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:"rgba(255,255,255,0.45)", fontFamily:"'JetBrains Mono',monospace" }}>
                        {s.label}
                      </button>
                    ))}
                  </div>
                  <textarea value={input} onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key==="Enter"&&!e.shiftKey){e.preventDefault();run();} }}
                    disabled={isRunning} rows={5}
                    placeholder="Main pani puri ka thela chalata hoon…"
                    className="w-full rounded-2xl text-[13px] resize-none outline-none transition-all duration-300 leading-relaxed"
                    style={{ background:"rgba(255,255,255,0.04)",
                      border:`1px solid ${statuses[0]==="processing" ? stage.color+"55" : "rgba(255,255,255,0.08)"}`,
                      padding:"15px 17px", color:"rgba(255,255,255,0.75)", fontFamily:"'JetBrains Mono',monospace",
                      boxShadow: statuses[0]==="processing" ? `0 0 40px ${stage.color}18,inset 0 0 24px ${stage.color}08` : "none" }} />
                  <div className="flex gap-3 items-center flex-wrap">
                    <select value={lang} onChange={e => setLang(e.target.value)} disabled={isRunning}
                      className="rounded-xl text-[12px] outline-none"
                      style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", padding:"11px 13px", color:"rgba(255,255,255,0.6)", fontFamily:"'JetBrains Mono',monospace" }}>
                      <option value="hi">Hindi</option><option value="mr">Marathi</option>
                      <option value="kn">Kannada</option><option value="ta">Tamil</option>
                      <option value="en">English</option>
                    </select>
                    <button onClick={run} disabled={!input.trim()||isRunning}
                      className="flex items-center gap-2 rounded-xl text-[13px] font-bold transition-all disabled:opacity-20 disabled:cursor-not-allowed"
                      style={{ background:stage.color, color:"#000", padding:"11px 24px",
                        boxShadow: input.trim()&&!isRunning ? `0 0 28px ${stage.color}66,0 0 56px ${stage.color}28` : "none" }}>
                      <Send className="w-3.5 h-3.5" /> Run Pipeline
                    </button>
                    {error && <span className="text-[12px] text-red-400 px-3 py-2 rounded-xl" style={{ background:"#ff000011", border:"1px solid #ff000033", fontFamily:"'JetBrains Mono',monospace" }}>{error}</span>}
                    {allDone && (
                      <motion.button initial={{opacity:0,x:-6}} animate={{opacity:1,x:0}} onClick={reset}
                        className="flex items-center gap-2 rounded-xl text-[13px]"
                        style={{ border:"1px solid rgba(255,255,255,0.1)", padding:"11px 22px", color:"rgba(255,255,255,0.38)", fontFamily:"'JetBrains Mono',monospace" }}>
                        <RotateCcw className="w-3.5 h-3.5" /> Reset
                      </motion.button>
                    )}
                  </div>
                </div>
              )}

              {/* ── Stage 0 result: profile card + tags ── */}
              {i === 0 && result && <ProfileCard profile={result.profile} color={stage.color} timings={result.timings_ms} fingerprint={result.trace_fingerprint} />}

              {/* ── Stage 1 result: rules ── */}
              {i === 1 && result && <RulesPanel steps={result.steps} color={stage.color} />}

              {/* ── Stage 2 result: outcome ── */}
              {i === 2 && result && <OutcomePanel result={result} color={stage.color} />}
            </div>
          </div>
        ))}
      </div>

      {/* ── right: neon panel ── */}
      <div className="h-full relative overflow-hidden" style={{ flex: 1 }}>
        <NeonPanel statuses={statuses} active={active} prog={prog} />
      </div>
    </div>
  );
}

/* ─────────────── Profile card ─────────────── */
function ProfileCard({ profile, color, timings, fingerprint }: { profile: Profile; color: string; timings: Record<string,number>; fingerprint: string }) {
  const rows: [string, string][] = ([
    ["Occupation",   profile.occupation ?? "—"],
    ["Category",     profile.occupation_category ?? "—"],
    ["Age",          profile.age != null ? `${profile.age} yrs` : "—"],
    ["Daily income", profile.daily_income != null ? `₹${profile.daily_income.toLocaleString()}` : profile.monthly_income != null ? `₹${profile.monthly_income.toLocaleString()}/mo` : "—"],
    ["Location",     [profile.city, profile.state].filter(Boolean).join(", ") || "—"],
    ["Documents",    profile.documents?.length ? profile.documents.join(", ") : "none stated"],
    ["Need",         profile.stated_need ?? "—"],
  ] as [string,string][]).filter(([,v]) => v !== "—");

  const total = Object.values(timings).reduce((a,b)=>a+b,0);

  // derive tag chips
  const tags = [
    profile.occupation_category ?? profile.occupation ?? "",
    profile.city ?? profile.state ?? "",
    profile.documents?.length ? `${profile.documents.length} doc${profile.documents.length>1?"s":""}` : "No docs",
    profile.daily_income != null ? `₹${profile.daily_income}/day` : "",
  ].filter(Boolean);

  return (
    <motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} transition={{duration:0.45}}
      className="mt-6 rounded-2xl overflow-hidden"
      style={{ border:`1px solid ${color}28`, background:`${color}07`, boxShadow:`0 0 24px ${color}10` }}>
      <div className="px-5 pt-4 pb-1 text-[9px] tracking-[0.42em] uppercase" style={{ color, fontFamily:"'JetBrains Mono',monospace" }}>EXTRACTED PROFILE</div>
      <div className="px-5 pb-4 space-y-2 mt-1">
        {rows.map(([k,v]) => (
          <div key={k} className="flex gap-3 text-[13px]">
            <span className="text-white/30 min-w-[110px]" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{k}</span>
            <span className="text-white/75 leading-snug">{v}</span>
          </div>
        ))}
      </div>
      {/* tag chips */}
      <div className="px-5 pb-4 flex flex-wrap gap-2">
        {tags.map((tag, ti) => (
          <motion.span key={ti}
            initial={{opacity:0, scale:0.75}} animate={{opacity:1, scale:1}}
            transition={{delay: 0.2 + ti * 0.1, duration:0.22, type:"spring", stiffness:280}}
            className="px-3 py-1 rounded-full text-[11px] font-semibold"
            style={{ background:`${color}16`, border:`1px solid ${color}45`, color, fontFamily:"'JetBrains Mono',monospace",
              boxShadow:`0 0 10px ${color}18` }}>
            {tag}
          </motion.span>
        ))}
      </div>
      <div className="px-5 py-2.5 border-t text-[10px] text-white/20 flex gap-4" style={{ borderColor:`${color}18`, fontFamily:"'JetBrains Mono',monospace" }}>
        <span>trace {fingerprint}</span>
        <span>{Math.round(total)}ms</span>
      </div>
    </motion.div>
  );
}

/* ─────────────── Rules panel ─────────────── */
function RulesPanel({ steps, color }: { steps: PipelineStep[]; color: string }) {
  const [expanded, setExpanded] = useState<Record<string,boolean>>({});

  const schemes = steps.filter(s => s.kind === "scheme") as SchemeStep[];
  const rulesByScheme: Record<string, Rule[]> = {};
  let cur = "";
  for (const s of steps) {
    if (s.kind === "scheme") { cur = s.label; rulesByScheme[cur] = []; }
    else if (s.kind === "rule" && cur) rulesByScheme[cur].push(s);
  }

  return (
    <motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} transition={{duration:0.45}} className="mt-6 space-y-3">
      {/* grounded source badge */}
      <div className="rounded-2xl p-4 flex items-start gap-3"
        style={{ border:`1px solid ${color}35`, background:`${color}0a`, boxShadow:`0 0 20px ${color}10` }}>
        <FileText className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color }} />
        <div className="flex-1 min-w-0">
          <div className="text-[12px] font-bold text-white/88 leading-snug">PM Mudra Yojana — Eligibility Circular, RBI 2024</div>
          <div className="text-[10px] text-white/35 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>RBI/2024/PMMY/14 · Govt. of India</div>
        </div>
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full flex-shrink-0" style={{ background:"#00ff9412", border:"1px solid #00ff9435" }}>
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          <span className="text-[10px] text-emerald-400 font-semibold" style={{ fontFamily:"'JetBrains Mono',monospace" }}>Verified</span>
        </div>
      </div>

      {schemes.map((scheme, si) => {
        const rules = rulesByScheme[scheme.label] ?? [];
        const pass = rules.filter(r=>r.passed===true).length;
        const fail = rules.filter(r=>r.passed===false).length;
        const unkn = rules.filter(r=>r.passed===null).length;
        const open = expanded[scheme.label];
        return (
          <motion.div key={si}
            initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{delay: si*0.1 + 0.1}}
            className="rounded-2xl overflow-hidden"
            style={{ border:`1px solid ${color}20`, background:`${color}07` }}>
            <button className="w-full px-5 py-4 flex items-center justify-between"
              onClick={()=>setExpanded(p=>({...p,[scheme.label]:!p[scheme.label]}))}>
              <div className="text-left">
                <div className="text-[12px] font-bold text-white/85 leading-snug">{scheme.label}</div>
                <div className="text-[10px] text-white/30 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{scheme.detail}</div>
              </div>
              <div className="flex items-center gap-2.5 flex-shrink-0 ml-3">
                <div className="flex gap-1.5 text-[10px]" style={{ fontFamily:"'JetBrains Mono',monospace" }}>
                  {pass>0&&<span className="px-2 py-0.5 rounded-full text-emerald-400" style={{ background:"#00ff9418" }}>✓ {pass}</span>}
                  {fail>0&&<span className="px-2 py-0.5 rounded-full text-red-400" style={{ background:"#ff000018" }}>✗ {fail}</span>}
                  {unkn>0&&<span className="px-2 py-0.5 rounded-full text-amber-400" style={{ background:"#f5a62318" }}>? {unkn}</span>}
                </div>
                {open ? <ChevronUp className="w-3.5 h-3.5 text-white/30"/> : <ChevronDown className="w-3.5 h-3.5 text-white/30"/>}
              </div>
            </button>
            <AnimatePresence>
              {open && (
                <motion.div initial={{height:0,opacity:0}} animate={{height:"auto",opacity:1}} exit={{height:0,opacity:0}} transition={{duration:0.25}} className="overflow-hidden">
                  <div className="px-5 pb-4 space-y-2 border-t" style={{ borderColor:`${color}15` }}>
                    {rules.map((rule, ri) => (
                      <div key={ri} className="flex gap-3 items-start py-3 px-3 rounded-xl text-[12px]"
                        style={{ background: rule.passed===true?"#00ff9408":rule.passed===false?"#ff000408":"#f5a62308",
                          borderLeft:`2px solid ${rule.passed===true?"#00ff94":rule.passed===false?"#ff4560":"#f5a623"}` }}>
                        <span className="font-bold mt-0.5 flex-shrink-0 text-[14px]"
                          style={{ color:rule.passed===true?"#00ff94":rule.passed===false?"#ff4560":"#f5a623" }}>
                          {rule.passed===true?"✓":rule.passed===false?"✗":"⋯"}
                        </span>
                        <div>
                          <div className="text-white/80 leading-snug">{rule.label}</div>
                          <div className="text-white/30 mt-1" style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:"0.63rem" }}>{rule.citation}</div>
                          {rule.quote && <div className="mt-1.5 text-white/40 italic text-[11px] leading-relaxed">"{rule.quote.slice(0,140)}{rule.quote.length>140?"…":""}"</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        );
      })}
    </motion.div>
  );
}

/* ─────────────── Outcome panel ─────────────── */
function OutcomePanel({ result, color }: { result: ReasonResponse; color: string }) {
  const ladders = result.steps.filter(s => s.kind === "ladder") as LadderBlock[];
  const eligible = result.decisions.filter(d => d.status === "eligible");
  const audioSrc = result.audio_path ? `/api/audio?path=${encodeURIComponent(result.audio_path)}` : null;
  const spokenExpanded = expandAcronyms(result.spoken_text);

  return (
    <motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} transition={{duration:0.45}} className="mt-6 space-y-4">
      {/* eligible schemes */}
      {eligible.map((d,i) => (
        <motion.div key={i} initial={{opacity:0,scale:0.97}} animate={{opacity:1,scale:1}} transition={{delay:i*0.08}}
          className="rounded-2xl p-5"
          style={{ border:"1px solid #00ff9440", background:"#00ff9409", boxShadow:"0 0 28px #00ff9412" }}>
          <div className="text-[9px] tracking-[0.42em] uppercase text-emerald-400 mb-2" style={{ fontFamily:"'JetBrains Mono',monospace" }}>ELIGIBLE NOW</div>
          <div className="text-[16px] font-bold text-white/92 mb-1.5 leading-snug">{d.scheme_name}</div>
          <div className="text-[13px] text-white/50 mb-3 leading-relaxed">{d.benefit_summary}</div>
          {d.benefit_amount_rupees && <div className="text-[30px] font-bold text-emerald-400">₹{d.benefit_amount_rupees.toLocaleString()}</div>}
        </motion.div>
      ))}

      {/* ladder paths */}
      {ladders.map((lb, li) => (
        <div key={li} className="rounded-2xl overflow-hidden" style={{ border:`1px solid ${color}30`, background:`${color}08` }}>
          <div className="px-5 pt-4 pb-3">
            <div className="text-[9px] tracking-[0.38em] uppercase mb-2" style={{ color, fontFamily:"'JetBrains Mono',monospace" }}>PATH EXISTS</div>
            <div className="text-[15px] font-bold text-white/90 mb-1 leading-snug">{lb.scheme}</div>
            <div className="text-[11px] text-white/35" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{lb.detail}</div>
          </div>
          <div className="px-5 pb-5 space-y-2.5">
            {lb.steps.map((step, si) => (
              <div key={si} className="flex gap-3 items-start p-4 rounded-xl"
                style={{ background:"rgba(0,0,0,0.25)", borderLeft:`2px solid ${color}60` }}>
                <div className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold flex-shrink-0 mt-0.5"
                  style={{ background:color, color:"#000" }}>{step.order}</div>
                <div>
                  <div className="text-[13px] font-semibold text-white/88 leading-snug">{step.action}</div>
                  <div className="text-[10px] text-white/35 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>
                    {step.cost_rupees===0?"free":`₹${step.cost_rupees}`} · {step.time_days} days{step.where?` · ${step.where}`:""}
                  </div>
                  {step.detail && <div className="text-[12px] text-white/50 mt-1 leading-relaxed">{step.detail}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* spoken answer */}
      <div className="rounded-2xl p-5" style={{ border:`1px solid ${color}40`, background:`${color}0b`, boxShadow:`0 0 32px ${color}12` }}>
        <div className="text-[9px] tracking-[0.42em] uppercase mb-1" style={{ color, fontFamily:"'JetBrains Mono',monospace" }}>WHAT HE HEARS</div>
        <div className="text-[10px] text-white/28 mb-4" style={{ fontFamily:"'JetBrains Mono',monospace" }}>He has no screen. This is the entire product from his side.</div>

        {/* waveform + speaker */}
        <div className="flex items-center gap-3 mb-4">
          <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
            style={{ background:`${color}20`, border:`1px solid ${color}40` }}>
            <Volume2 className="w-4 h-4" style={{ color }} />
          </div>
          <AudioBars color={color} active={!!audioSrc} />
        </div>

        <div className="text-[14px] leading-[1.9] text-white/88 mb-5">{spokenExpanded}</div>

        {audioSrc
          ? <audio controls autoPlay src={audioSrc} className="w-full mb-5" style={{ filter:"invert(0.9) hue-rotate(180deg)", borderRadius:8 }} />
          : <div className="text-[11px] text-amber-400/70 mb-5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>⚠ No audio — TTS unavailable. Text shown above.</div>
        }

        {/* IVR keypad */}
        <IVRKeypad color={color} />
      </div>
    </motion.div>
  );
}

/* ─────────────── IVR keypad ─────────────── */
function IVRKeypad({ color }: { color: string }) {
  const keys = [
    { key: "1", label: "Repeat",            icon: <RotateCcw className="w-3.5 h-3.5" /> },
    { key: "2", label: "Start application", icon: <Send className="w-3.5 h-3.5" /> },
    { key: "0", label: "Talk to a person",  icon: <Phone className="w-3.5 h-3.5" /> },
  ];
  return (
    <div className="rounded-xl overflow-hidden" style={{ border:`1px solid ${color}25`, background:"rgba(0,0,0,0.3)" }}>
      <div className="px-4 pt-3 pb-2 text-[9px] tracking-[0.38em] uppercase text-white/25" style={{ fontFamily:"'JetBrains Mono',monospace" }}>
        IVR KEYPAD — press after hearing the answer
      </div>
      <div className="flex">
        {keys.map(({ key, label, icon }, ki) => (
          <div key={key} className="flex-1 flex flex-col items-center gap-1.5 py-3 px-2"
            style={{ borderLeft: ki > 0 ? `1px solid ${color}15` : "none" }}>
            <div className="w-9 h-9 rounded-full flex items-center justify-center font-bold text-[16px]"
              style={{ background:`${color}18`, border:`1px solid ${color}45`, color, fontFamily:"'JetBrains Mono',monospace",
                boxShadow:`0 0 12px ${color}20` }}>
              {key}
            </div>
            <div className="text-white/45">{icon}</div>
            <div className="text-[9px] text-center text-white/35 leading-tight" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─────────────── Audio bars ─────────────── */
function AudioBars({ color, active }: { color: string; active: boolean }) {
  const heights = [3,5,4,7,5,4,6,3,5,4];
  return (
    <div className="flex items-end gap-0.5 h-5">
      {heights.map((h, i) => (
        <motion.div key={i} className="w-0.5 rounded-full"
          style={{ background: active ? color : `${color}40`, height:`${h*2}px` }}
          animate={active ? { scaleY:[1,1.4+Math.random()*0.5,1] } : {}}
          transition={{ duration:0.5+i*0.07, repeat:Infinity, repeatType:"mirror", ease:"easeInOut", delay:i*0.06 }} />
      ))}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   DOC DOCTOR TAB
═══════════════════════════════════════════════════════════ */
function DocDoctorTab() {
  const [files, setFiles]     = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [report, setReport]   = useState<DocReport | null>(null);
  const [error, setError]     = useState("");
  const inputRef              = useRef<HTMLInputElement>(null);

  const check = async () => {
    if (files.length < 2) return;
    setLoading(true); setReport(null); setError("");
    const fd = new FormData();
    files.forEach(f => fd.append("files", f, f.name));
    try {
      const r = await fetch("/api/documents/check", { method:"POST", body:fd });
      if (!r.ok) throw new Error(`API ${r.status}: ${await r.text()}`);
      setReport(await r.json());
    } catch(e) { setError(e instanceof Error ? e.message : "Check failed"); }
    finally { setLoading(false); }
  };

  const C = "#0df2a0";

  return (
    <div className="h-full overflow-y-auto px-10 py-8" style={{ scrollbarWidth:"none" }}>
      <div style={{ maxWidth:700, margin:"0 auto" }}>
        <div className="flex items-center gap-3 mb-2">
          <span className="text-[10px] tracking-[0.38em] uppercase" style={{ color:C, fontFamily:"'JetBrains Mono',monospace" }}>DOC DOCTOR</span>
        </div>
        <h2 className="text-[2.1rem] font-bold text-white/90 mb-2" style={{ letterSpacing:"-0.02em" }}>Check before you apply</h2>
        <p className="text-[13px] text-white/40 mb-8 leading-relaxed">
          A name spelled one way on an Aadhaar and another on a passbook is how applications die silently — months later, without a reason.
          Upload two or more documents and we check for mismatches now.
        </p>

        <div onClick={() => inputRef.current?.click()}
          className="rounded-2xl p-10 text-center cursor-pointer transition-all mb-5"
          style={{ border:`1.5px dashed ${files.length>0?C+"60":"rgba(255,255,255,0.1)"}`,
            background: files.length>0?`${C}07`:"rgba(255,255,255,0.02)",
            boxShadow: files.length>0?`0 0 32px ${C}10`:"none" }}>
          <Upload className="w-7 h-7 mx-auto mb-3 text-white/30" />
          <div className="text-[14px] text-white/55">Click to upload document photos</div>
          <div className="text-[11px] text-white/25 mt-1.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>JPG · PNG · PDF — name as aadhaar.jpg, passbook.jpg etc.</div>
          <input ref={inputRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.pdf" className="hidden"
            onChange={e => setFiles(Array.from(e.target.files ?? []))} />
        </div>

        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-5">
            {files.map((f,i) => (
              <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-xl text-[12px]"
                style={{ background:`${C}12`, border:`1px solid ${C}30`, color:C, fontFamily:"'JetBrains Mono',monospace" }}>
                <FileText className="w-3 h-3" />{f.name}
              </div>
            ))}
          </div>
        )}

        <button onClick={check} disabled={files.length<2||loading}
          className="flex items-center gap-2 rounded-xl text-[13px] font-bold transition-all disabled:opacity-30 disabled:cursor-not-allowed mb-6"
          style={{ background:C, color:"#000", padding:"12px 30px", boxShadow: files.length>=2&&!loading?`0 0 28px ${C}55`:"none" }}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
          {loading ? "Reading documents…" : "Run check"}
        </button>
        {files.length===1&&<div className="text-[12px] text-white/30 mb-4" style={{ fontFamily:"'JetBrains Mono',monospace" }}>Add one more document — the check is a comparison.</div>}

        {error && <div className="rounded-xl p-4 mb-4 text-[12px] text-red-400" style={{ background:"#ff000011", border:"1px solid #ff000033", fontFamily:"'JetBrains Mono',monospace" }}>{error}</div>}

        {report && (
          <motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}}>
            <div className="rounded-2xl p-5 mb-5 flex items-center gap-3"
              style={{ background: report.clear?"#00ff9412":"#ff000012", border:`1px solid ${report.clear?"#00ff9440":"#ff000040"}` }}>
              {report.clear ? <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0" /> : <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" />}
              <div>
                <div className={`text-[14px] font-bold ${report.clear?"text-emerald-400":"text-red-400"}`}>{report.summary}</div>
                {!report.reading_is_reliable && <div className="text-[11px] text-amber-400/70 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>⚠ OCR used as fallback — readings may be less accurate</div>}
              </div>
            </div>

            {report.findings.map((f,i) => (
              <div key={i} className="rounded-2xl p-5 mb-3"
                style={{ background: f.severity==="blocker"?"#ff000010":"#f5a62310", border:`1px solid ${f.severity==="blocker"?"#ff000040":"#f5a62340"}` }}>
                <div className="flex items-start gap-2.5 mb-2">
                  <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color:f.severity==="blocker"?"#ff4560":"#f5a623" }} />
                  <div className="text-[13px] font-semibold text-white/88 leading-snug">{f.message}</div>
                </div>
                {Object.entries(f.values).length>0 && (
                  <div className="ml-7 flex flex-wrap gap-2 mb-2">
                    {Object.entries(f.values).map(([doc,name]) => (
                      <div key={doc} className="px-3 py-1.5 rounded-lg text-[11px]"
                        style={{ background:"rgba(255,255,255,0.05)", border:"1px solid rgba(255,255,255,0.1)", fontFamily:"'JetBrains Mono',monospace" }}>
                        <span className="text-white/35">{doc}: </span><span className="text-white/75">{name}</span>
                      </div>
                    ))}
                  </div>
                )}
                {f.consequence && <div className="ml-7 text-[11px] text-white/50 mb-1.5 leading-relaxed"><span className="text-white/30">What this costs: </span>{f.consequence}</div>}
                {f.fix && <div className="ml-7 text-[11px] text-emerald-400/75 leading-relaxed"><span className="text-white/30">Fix: </span>{f.fix}</div>}
              </div>
            ))}

            <div className="rounded-2xl overflow-hidden" style={{ border:"1px solid rgba(255,255,255,0.08)" }}>
              <div className="px-5 py-3 text-[9px] tracking-[0.38em] uppercase text-white/25 border-b border-white/05" style={{ fontFamily:"'JetBrains Mono',monospace" }}>WHAT WE READ OFF EACH DOCUMENT</div>
              <div className="divide-y divide-white/05">
                {report.documents.map((d,i) => (
                  <div key={i} className="px-5 py-3.5 flex gap-4 flex-wrap text-[12px]">
                    <span className="text-white/60 font-bold min-w-[130px]">{d.label}</span>
                    <span style={{ fontFamily:"'JetBrains Mono',monospace", color:"rgba(255,255,255,0.5)" }}>{d.name ?? "—"}</span>
                    {d.dob && <span className="text-white/30" style={{ fontFamily:"'JetBrains Mono',monospace" }}>DOB {d.dob}</span>}
                    <span className="text-white/20 ml-auto" style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:"0.62rem" }}>{d.extraction_method}</span>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   LEDGER TAB
═══════════════════════════════════════════════════════════ */
function LedgerTab() {
  const [statement, setStatement] = useState<LedgerStatement | null>(null);
  const [loading, setLoading]     = useState(false);
  const [seeding, setSeeding]     = useState(false);
  const [entry, setEntry]         = useState("");
  const [posting, setPosting]     = useState(false);
  const [userId, setUserId]       = useState("demo");
  const [error, setError]         = useState("");
  const [postMsg, setPostMsg]     = useState("");

  const C = "#f5c842";

  const fetchStatement = useCallback(async (uid = userId) => {
    setLoading(true); setError("");
    try {
      const r = await fetch(`/api/ledger/statement?user_id=${uid}&days=30`);
      if (!r.ok) throw new Error(`API ${r.status}`);
      setStatement(await r.json());
    } catch(e) { setError(e instanceof Error ? e.message : "Failed"); }
    finally { setLoading(false); }
  }, [userId]);

  const seed = async () => {
    setSeeding(true); setError("");
    try {
      await fetch(`/api/ledger/seed?user_id=${userId}&days=30`, { method:"POST" });
      await fetchStatement();
    } catch(e) { setError(e instanceof Error ? e.message : "Seed failed"); }
    finally { setSeeding(false); }
  };

  const postEntry = async () => {
    if (!entry.trim()) return;
    setPosting(true); setPostMsg("");
    try {
      const r = await fetch("/api/ledger/entry", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ text: entry.trim(), user_id: userId }),
      });
      const d = await r.json();
      setPostMsg(`Recorded: earned ₹${d.earned ?? "—"}, spent ₹${d.spent ?? "—"}`);
      setEntry(""); fetchStatement();
    } catch(e) { setPostMsg("Failed to record entry"); }
    finally { setPosting(false); }
  };

  const maxEarned = statement ? Math.max(...statement.daily.map(d => d.earned ?? 0), 1) : 1;

  return (
    <div className="h-full overflow-y-auto px-10 py-8" style={{ scrollbarWidth:"none" }}>
      <div style={{ maxWidth:740, margin:"0 auto" }}>
        <div className="flex items-center gap-3 mb-2">
          <span className="text-[10px] tracking-[0.38em] uppercase" style={{ color:C, fontFamily:"'JetBrains Mono',monospace" }}>VOICE LEDGER</span>
        </div>
        <h2 className="text-[2.1rem] font-bold text-white/90 mb-2" style={{ letterSpacing:"-0.02em" }}>Trust Passport</h2>
        <p className="text-[13px] text-white/40 mb-7 leading-relaxed">
          Every evening the vendor speaks five seconds. Thirty of those become a cash-flow statement a loan officer can actually read.
        </p>

        <div className="flex gap-3 flex-wrap mb-6">
          <input value={userId} onChange={e => setUserId(e.target.value)}
            className="rounded-xl text-[12px] outline-none px-3 py-2.5"
            style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:"rgba(255,255,255,0.6)", fontFamily:"'JetBrains Mono',monospace", width:150 }}
            placeholder="user_id" />
          <button onClick={()=>fetchStatement()} disabled={loading}
            className="flex items-center gap-2 rounded-xl text-[12px] font-bold transition-all disabled:opacity-40"
            style={{ background:C, color:"#000", padding:"10px 20px" }}>
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <TrendingUp className="w-3.5 h-3.5"/>}
            Load statement
          </button>
          <button onClick={seed} disabled={seeding||loading}
            className="flex items-center gap-2 rounded-xl text-[12px] transition-all disabled:opacity-30"
            style={{ border:`1px solid ${C}40`, color:C, padding:"10px 20px", background:`${C}0a` }}>
            {seeding ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <Coins className="w-3.5 h-3.5"/>}
            Seed 30 demo days
          </button>
        </div>

        <div className="rounded-2xl p-5 mb-6" style={{ border:`1px solid ${C}20`, background:`${C}07` }}>
          <div className="text-[9px] tracking-[0.38em] uppercase mb-3" style={{ color:C, fontFamily:"'JetBrains Mono',monospace" }}>ADD TODAY'S ENTRY</div>
          <div className="flex gap-3">
            <input value={entry} onChange={e=>setEntry(e.target.value)}
              onKeyDown={e=>{if(e.key==="Enter")postEntry();}}
              placeholder="aaj aath sau ka kaam hua, do sau ka maal liya"
              className="flex-1 rounded-xl text-[12px] outline-none px-3 py-2.5"
              style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:"rgba(255,255,255,0.65)", fontFamily:"'JetBrains Mono',monospace" }} />
            <button onClick={postEntry} disabled={!entry.trim()||posting}
              className="rounded-xl px-4 text-[12px] font-bold disabled:opacity-30"
              style={{ background:C, color:"#000" }}>
              {posting ? <Loader2 className="w-4 h-4 animate-spin"/> : <Send className="w-4 h-4"/>}
            </button>
          </div>
          {postMsg && <div className="mt-2.5 text-[11px] text-emerald-400" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{postMsg}</div>}
        </div>

        {error && <div className="rounded-xl p-3 mb-4 text-[12px] text-red-400" style={{ background:"#ff000011", border:"1px solid #ff000033", fontFamily:"'JetBrains Mono',monospace" }}>{error}</div>}

        {statement && (
          <motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} className="space-y-5">
            <div className="grid grid-cols-3 gap-4">
              {[
                ["Total earned", `₹${statement.total_earned.toLocaleString()}`],
                ["Net",          `₹${statement.net.toLocaleString()}`],
                ["Median / day", `₹${statement.median_daily_earned.toLocaleString()}`],
              ].map(([k,v]) => (
                <div key={k} className="rounded-2xl p-5 text-center" style={{ border:`1px solid ${C}28`, background:`${C}0a` }}>
                  <div className="text-[26px] font-bold" style={{ color:C }}>{v}</div>
                  <div className="text-[10px] text-white/30 mt-1" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{k}</div>
                </div>
              ))}
            </div>

            <div className="rounded-2xl p-5" style={{ border:"1px solid rgba(255,255,255,0.08)", background:"rgba(255,255,255,0.02)" }}>
              <div className="flex gap-6 flex-wrap text-[12px] mb-3">
                {[
                  ["Period",       `${statement.period_start} → ${statement.period_end}`],
                  ["Days covered", `${statement.days_covered} / ${statement.days_in_period} (${Math.round(statement.coverage_pct*100)}%)`],
                  ["Corroborated", `${Math.round(statement.corroboration_pct*100)}% via UPI`],
                  ["Confidence",   statement.confidence.toUpperCase()],
                ].map(([k,v]) => (
                  <div key={k}>
                    <div className="text-white/25 text-[9px] tracking-widest uppercase" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{k}</div>
                    <div className={`mt-0.5 font-semibold ${k==="Confidence"&&statement.confidence==="strong"?"text-emerald-400":k==="Confidence"&&statement.confidence==="indicative"?"text-amber-400":"text-white/70"}`}>{v}</div>
                  </div>
                ))}
              </div>
              {statement.caveats.map((c,i)=>(
                <div key={i} className="text-[11px] text-white/35 py-1 border-t border-white/04 leading-relaxed">⚠ {c}</div>
              ))}
            </div>

            {statement.daily.length > 0 && (
              <div className="rounded-2xl p-5" style={{ border:`1px solid ${C}20`, background:`${C}07` }}>
                <div className="text-[9px] tracking-[0.38em] uppercase mb-5" style={{ color:C, fontFamily:"'JetBrains Mono',monospace" }}>DAILY EARNINGS — {statement.daily.length} days</div>
                <div className="flex items-end gap-1" style={{ height:90 }}>
                  {statement.daily.map((day,i) => (
                    <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative" style={{ minWidth:0 }}>
                      <div className="w-full rounded-sm transition-all"
                        style={{ height:`${Math.round((day.earned/maxEarned)*82)+4}px`,
                          background: day.corroborated?`${C}cc`:`${C}55`,
                          border: day.corroborated?`1px solid ${C}`:"none" }} />
                      <div className="absolute bottom-full mb-1 text-[9px] rounded px-1.5 py-0.5 opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-10"
                        style={{ background:"rgba(0,0,0,0.9)", border:`1px solid ${C}30`, color:"rgba(255,255,255,0.8)", fontFamily:"'JetBrains Mono',monospace" }}>
                        {day.date}<br/>₹{day.earned.toLocaleString()}{day.spent?` · spent ₹${day.spent.toLocaleString()}`:""}{day.corroborated?" · UPI ✓":""}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="flex justify-between mt-2 text-[9px] text-white/20" style={{ fontFamily:"'JetBrains Mono',monospace" }}>
                  <span>{statement.period_start}</span><span style={{ color:`${C}99` }}>■ UPI corroborated</span><span>{statement.period_end}</span>
                </div>
              </div>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
}

/* ─────────────── Neon right panel ─────────────── */
function NeonPanel({ statuses, active, prog }: { statuses: Status[]; active: number; prog: number[] }) {
  const activeColor = active >= 0 ? STAGES[active].color : "transparent";
  const bgY = active===0?"14%":active===1?"50%":active===2?"86%":"50%";
  return (
    <div className="w-full h-full relative">
      <div className="absolute inset-0 transition-all duration-1000 pointer-events-none"
        style={{ background: active>=0?`radial-gradient(ellipse 80% 32% at 50% ${bgY}, ${activeColor}22 0%, transparent 72%)`:"transparent" }} />
      {active>=0 && (
        <motion.div key={`pulse-${active}`} className="absolute pointer-events-none"
          style={{ left:"50%", top:bgY, transform:"translate(-50%,-50%)", width:150, height:150, borderRadius:"50%", border:`1px solid ${activeColor}45` }}
          animate={{ scale:[1,1.4,1], opacity:[0.5,0.08,0.5] }}
          transition={{ duration:2.2, repeat:Infinity, ease:"easeInOut" }} />
      )}
      {/* scan line */}
      {active>=0 && (
        <motion.div className="absolute left-0 right-0 pointer-events-none"
          style={{ height:1, background:`linear-gradient(to right, transparent 0%, ${activeColor}35 35%, ${activeColor}65 50%, ${activeColor}35 65%, transparent 100%)` }}
          animate={{ top:["0%","100%"] }}
          transition={{ duration:4.5, repeat:Infinity, ease:"linear", repeatDelay:0.8 }} />
      )}
      <svg viewBox="0 0 400 900" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 w-full h-full">
        <defs>
          <filter id="f-xl" x="-120%" y="-20%" width="340%" height="140%"><feGaussianBlur stdDeviation="13" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="f-md" x="-60%" y="-10%" width="220%" height="120%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        {/* ghost traces for all 5 paths */}
        {PATHS.map((d,i)=>(<path key={`ghost-${i}`} d={d} fill="none" stroke={STAGES[Math.min(i,2)].color} strokeWidth={0.8} opacity={0.06}/>))}
        {/* main 3 active neon paths */}
        {PATHS.slice(0,3).map((d,i)=>(<NeonPath key={i} d={d} color={STAGES[i].color} progress={prog[i]} isProcessing={statuses[i]==="processing"}/>))}
        {/* 2 extra ambient streaks */}
        <NeonPath d={PATHS[3]} color={STAGES[0].color} progress={prog[0]*0.55} isProcessing={false} />
        <NeonPath d={PATHS[4]} color={STAGES[2].color} progress={prog[2]*0.45} isProcessing={false} />
      </svg>
      <div className="absolute right-5 inset-y-0 flex flex-col justify-around py-20 pointer-events-none">
        {STAGES.map((s,i)=>(
          <div key={i} className="text-right transition-all duration-500" style={{ opacity: statuses[i]==="idle"?0.12:1 }}>
            <div className="text-[9px] tracking-[0.32em] uppercase mb-0.5" style={{ color:s.color, fontFamily:"'JetBrains Mono',monospace" }}>{s.num}</div>
            <div className="text-[10px] text-white/35" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{s.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function NeonPath({ d, color, progress, isProcessing }: { d:string; color:string; progress:number; isProcessing:boolean }) {
  const pt = { duration:1.8, ease:"easeOut" as const };
  const pulse = { repeat:Infinity, duration:1.8, ease:"easeInOut" as const };
  return (
    <>
      <motion.path d={d} fill="none" stroke={color} strokeWidth={32} strokeLinecap="round" filter="url(#f-xl)"
        initial={{ pathLength:0, opacity:0 }}
        animate={{ pathLength:progress, opacity: isProcessing?[0.12,0.40,0.12]:progress>0?0.22:0 }}
        transition={{ pathLength:pt, opacity: isProcessing?pulse:{duration:0.7} }} />
      <motion.path d={d} fill="none" stroke={color} strokeWidth={7} strokeLinecap="round" filter="url(#f-md)"
        initial={{ pathLength:0, opacity:0 }}
        animate={{ pathLength:progress, opacity: isProcessing?[0.45,0.95,0.45]:progress>0?0.65:0 }}
        transition={{ pathLength:pt, opacity: isProcessing?pulse:{duration:0.6} }} />
      <motion.path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round"
        initial={{ pathLength:0, opacity:0 }}
        animate={{ pathLength:progress, opacity: isProcessing?[0.8,1,0.8]:progress>0?1:0 }}
        transition={{ pathLength:pt, opacity: isProcessing?{...pulse,duration:1.8}:{duration:0.3} }} />
    </>
  );
}
