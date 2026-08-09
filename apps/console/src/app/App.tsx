import { useState, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Mic, Database, Volume2, Send, RotateCcw, CheckCircle2,
  Loader2, Activity, FileText, TrendingUp, Upload, AlertTriangle,
  CheckCircle, XCircle, ChevronDown, ChevronUp, Coins,
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
];

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

      {/* tab content */}
      <div className="pt-[52px] h-full">
        {tab === "pipeline" && <PipelineTab />}
        {tab === "doctor"   && <DocDoctorTab />}
        {tab === "ledger"   && <LedgerTab />}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════
   PIPELINE TAB
═══════════════════════════════════════════════════════════ */
function PipelineTab() {
  const [input, setInput]     = useState("");
  const [statuses, setStatuses] = useState<Status[]>(["idle","idle","idle"]);
  const [active, setActive]   = useState(-1);
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult]   = useState<ReasonResponse | null>(null);
  const [error, setError]     = useState("");
  const [lang, setLang]       = useState("hi");
  const abortRef              = useRef(false);
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
    await pause(700);
    if (abortRef.current) return;

    setStatuses(["complete","complete","processing"]); setActive(2);
    setTimeout(() => scrollTo(2), 420);
    await pause(700);
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
      {/* left scroll */}
      <div className="h-full overflow-y-scroll snap-y snap-mandatory" style={{ width: "60%", scrollbarWidth: "none" }}>
        {STAGES.map((stage, i) => (
          <div key={i} ref={refs[i]} className="snap-start relative flex flex-col justify-center"
            style={{ height: "calc(100dvh - 52px)", paddingLeft: "clamp(2.5rem,7vw,4rem)", paddingRight: "2rem" }}>

            {i < 2 && (
              <div className="absolute bottom-0 transition-all duration-700"
                style={{ left:"clamp(2.5rem,7vw,4rem)", width:1, height:80,
                  background: `linear-gradient(to bottom, ${stage.color}50, transparent)`,
                  opacity: statuses[i] === "complete" ? 1 : 0.1 }} />
            )}

            <div style={{ maxWidth: 520 }}>
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

              <div className="flex items-center gap-2.5 mb-7">
                {statuses[i] === "processing" ? <Loader2 className="w-3 h-3 animate-spin" style={{ color: stage.color }} />
                  : statuses[i] === "complete" ? <CheckCircle2 className="w-3 h-3" style={{ color: stage.color }} />
                  : <stage.Icon className="w-3 h-3 text-white/16" />}
                <span className="text-[12px] transition-colors duration-300" style={{
                  fontFamily:"'JetBrains Mono',monospace",
                  color: statuses[i]==="processing" ? stage.color : statuses[i]==="complete" ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.16)",
                }}>
                  {statuses[i]==="idle" ? stage.idle : statuses[i]==="processing" ? stage.running : stage.done}
                </span>
              </div>

              {/* stage 0 — input */}
              {i === 0 && (
                <div className="space-y-3">
                  <div className="flex gap-2 flex-wrap mb-1">
                    {SAMPLES.map((s,si) => (
                      <button key={si} onClick={() => setInput(s.text)} disabled={isRunning}
                        className="text-[11px] px-3 py-1 rounded-lg transition-all disabled:opacity-30"
                        style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:"rgba(255,255,255,0.45)", fontFamily:"'JetBrains Mono',monospace" }}>
                        {s.label}
                      </button>
                    ))}
                  </div>
                  <textarea value={input} onChange={e => setInput(e.target.value)}
                    onKeyDown={e => { if (e.key==="Enter"&&!e.shiftKey){e.preventDefault();run();} }}
                    disabled={isRunning} rows={4}
                    placeholder="Main pani puri ka thela chalata hoon…"
                    className="w-full rounded-xl text-[13px] resize-none outline-none transition-all duration-300"
                    style={{ background:"rgba(255,255,255,0.04)", border:`1px solid ${statuses[0]==="processing" ? stage.color+"55" : "rgba(255,255,255,0.08)"}`,
                      padding:"13px 15px", color:"rgba(255,255,255,0.65)", fontFamily:"'JetBrains Mono',monospace",
                      boxShadow: statuses[0]==="processing" ? `0 0 30px ${stage.color}14,inset 0 0 20px ${stage.color}07` : "none" }} />
                  <div className="flex gap-3 items-center flex-wrap">
                    <select value={lang} onChange={e => setLang(e.target.value)} disabled={isRunning}
                      className="rounded-xl text-[12px] outline-none"
                      style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", padding:"10px 12px", color:"rgba(255,255,255,0.6)", fontFamily:"'JetBrains Mono',monospace" }}>
                      <option value="hi">Hindi</option><option value="mr">Marathi</option>
                      <option value="kn">Kannada</option><option value="ta">Tamil</option>
                      <option value="en">English</option>
                    </select>
                    <button onClick={run} disabled={!input.trim()||isRunning}
                      className="flex items-center gap-2 rounded-xl text-[13px] font-bold transition-all disabled:opacity-20 disabled:cursor-not-allowed"
                      style={{ background:stage.color, color:"#000", padding:"10px 22px",
                        boxShadow: input.trim()&&!isRunning ? `0 0 28px ${stage.color}55,0 0 56px ${stage.color}22` : "none" }}>
                      <Send className="w-3 h-3" /> Run Pipeline
                    </button>
                    {error && <span className="text-[12px] text-red-400 px-3 py-2 rounded-xl" style={{ background:"#ff000011", border:"1px solid #ff000033", fontFamily:"'JetBrains Mono',monospace" }}>{error}</span>}
                    {allDone && (
                      <motion.button initial={{opacity:0,x:-6}} animate={{opacity:1,x:0}} onClick={reset}
                        className="flex items-center gap-2 rounded-xl text-[13px]"
                        style={{ border:"1px solid rgba(255,255,255,0.1)", padding:"10px 22px", color:"rgba(255,255,255,0.38)", fontFamily:"'JetBrains Mono',monospace" }}>
                        <RotateCcw className="w-3 h-3" /> Reset
                      </motion.button>
                    )}
                  </div>
                </div>
              )}

              {/* stage 0 — profile card */}
              {i === 0 && result && <ProfileCard profile={result.profile} color={stage.color} timings={result.timings_ms} fingerprint={result.trace_fingerprint} />}

              {/* stage 1 — rules */}
              {i === 1 && result && <RulesPanel steps={result.steps} color={stage.color} />}

              {/* stage 2 — outcome */}
              {i === 2 && result && <OutcomePanel result={result} color={stage.color} />}
            </div>
          </div>
        ))}
      </div>

      {/* right neon panel */}
      <div className="h-full relative overflow-hidden" style={{ flex: 1 }}>
        <NeonPanel statuses={statuses} active={active} prog={prog} />
      </div>
    </div>
  );
}

/* ─────────────── Profile card ─────────────── */
function ProfileCard({ profile, color, timings, fingerprint }: { profile: Profile; color: string; timings: Record<string,number>; fingerprint: string }) {
  const rows: [string, string][] = [
    ["Occupation",  profile.occupation ?? "—"],
    ["Category",    profile.occupation_category ?? "—"],
    ["Age",         profile.age != null ? `${profile.age} yrs` : "—"],
    ["Daily income",profile.daily_income != null ? `₹${profile.daily_income.toLocaleString()}` : profile.monthly_income != null ? `₹${profile.monthly_income.toLocaleString()}/mo` : "—"],
    ["Location",    [profile.city, profile.state].filter(Boolean).join(", ") || "—"],
    ["Documents",   profile.documents?.length ? profile.documents.join(", ") : "none stated"],
    ["Need",        profile.stated_need ?? "—"],
  ].filter(([,v]) => v !== "—") as [string,string][];

  const total = Object.values(timings).reduce((a,b)=>a+b,0);

  return (
    <motion.div initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{duration:0.4}}
      className="mt-5 rounded-xl overflow-hidden"
      style={{ border:`1px solid ${color}25`, background:`${color}07` }}>
      <div className="px-4 pt-3 pb-1 text-[9px] tracking-[0.38em] uppercase" style={{ color, fontFamily:"'JetBrains Mono',monospace" }}>EXTRACTED PROFILE</div>
      <div className="px-4 pb-3 space-y-1.5">
        {rows.map(([k,v]) => (
          <div key={k} className="flex gap-3 text-[12px]">
            <span className="text-white/30 min-w-[100px]" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{k}</span>
            <span className="text-white/70">{v}</span>
          </div>
        ))}
      </div>
      <div className="px-4 py-2 border-t text-[10px] text-white/20 flex gap-4" style={{ borderColor:`${color}18`, fontFamily:"'JetBrains Mono',monospace" }}>
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
    <motion.div initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{duration:0.4}} className="mt-5 space-y-3">
      {schemes.map((scheme, si) => {
        const rules = rulesByScheme[scheme.label] ?? [];
        const pass = rules.filter(r=>r.passed===true).length;
        const fail = rules.filter(r=>r.passed===false).length;
        const unkn = rules.filter(r=>r.passed===null).length;
        const open = expanded[scheme.label];
        return (
          <div key={si} className="rounded-xl overflow-hidden" style={{ border:`1px solid ${color}20`, background:`${color}07` }}>
            <button className="w-full px-4 py-3 flex items-center justify-between" onClick={()=>setExpanded(p=>({...p,[scheme.label]:!p[scheme.label]}))}>
              <div className="text-left">
                <div className="text-[11px] font-bold text-white/80">{scheme.label}</div>
                <div className="text-[10px] text-white/30 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{scheme.detail}</div>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex gap-1.5 text-[10px]" style={{ fontFamily:"'JetBrains Mono',monospace" }}>
                  {pass>0&&<span className="text-emerald-400">✓{pass}</span>}
                  {fail>0&&<span className="text-red-400">✗{fail}</span>}
                  {unkn>0&&<span className="text-amber-400">?{unkn}</span>}
                </div>
                {open ? <ChevronUp className="w-3.5 h-3.5 text-white/30"/> : <ChevronDown className="w-3.5 h-3.5 text-white/30"/>}
              </div>
            </button>
            <AnimatePresence>
              {open && (
                <motion.div initial={{height:0,opacity:0}} animate={{height:"auto",opacity:1}} exit={{height:0,opacity:0}} transition={{duration:0.25}} className="overflow-hidden">
                  <div className="px-4 pb-3 space-y-1.5 border-t" style={{ borderColor:`${color}15` }}>
                    {rules.map((rule, ri) => (
                      <div key={ri} className="flex gap-2.5 items-start py-1.5 px-2 rounded-lg text-[11px]"
                        style={{ background: rule.passed===true?"#00ff9408":rule.passed===false?"#ff000408":"#f5a62308",
                          borderLeft:`2px solid ${rule.passed===true?"#00ff94":rule.passed===false?"#ff4560":"#f5a623"}` }}>
                        <span className="font-bold mt-0.5 flex-shrink-0" style={{ color:rule.passed===true?"#00ff94":rule.passed===false?"#ff4560":"#f5a623" }}>
                          {rule.passed===true?"✓":rule.passed===false?"✗":"⋯"}
                        </span>
                        <div>
                          <div className="text-white/75">{rule.label}</div>
                          <div className="text-white/30 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:"0.65rem" }}>{rule.citation}</div>
                          {rule.quote && <div className="mt-1 text-white/40 italic text-[10px]">"{rule.quote.slice(0,120)}{rule.quote.length>120?"…":""}"</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
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

  return (
    <motion.div initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{duration:0.4}} className="mt-5 space-y-4">
      {/* eligible now */}
      {eligible.map((d,i) => (
        <div key={i} className="rounded-xl p-4" style={{ border:`1px solid #00ff9430`, background:"#00ff9408" }}>
          <div className="text-[9px] tracking-[0.38em] uppercase text-emerald-400 mb-2" style={{ fontFamily:"'JetBrains Mono',monospace" }}>ELIGIBLE NOW</div>
          <div className="text-[15px] font-bold text-white/90 mb-1">{d.scheme_name}</div>
          <div className="text-[12px] text-white/45 mb-3">{d.benefit_summary}</div>
          {d.benefit_amount_rupees && <div className="text-[24px] font-bold text-emerald-400">₹{d.benefit_amount_rupees.toLocaleString()}</div>}
        </div>
      ))}

      {/* ladders */}
      {ladders.map((lb, li) => (
        <div key={li} className="rounded-xl overflow-hidden" style={{ border:`1px solid ${color}30`, background:`${color}08` }}>
          <div className="px-4 pt-3 pb-2">
            <div className="text-[9px] tracking-[0.38em] uppercase mb-2" style={{ color, fontFamily:"'JetBrains Mono',monospace" }}>PATH EXISTS</div>
            <div className="text-[15px] font-bold text-white/90 mb-0.5">{lb.scheme}</div>
            <div className="text-[11px] text-white/35" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{lb.detail}</div>
          </div>
          <div className="px-4 pb-4 space-y-2">
            {lb.steps.map((step, si) => (
              <div key={si} className="flex gap-3 items-start p-3 rounded-lg" style={{ background:"rgba(0,0,0,0.25)", borderLeft:`2px solid ${color}60` }}>
                <div className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 mt-0.5"
                  style={{ background:color, color:"#000" }}>{step.order}</div>
                <div>
                  <div className="text-[12px] font-semibold text-white/85">{step.action}</div>
                  <div className="text-[10px] text-white/35 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>
                    {step.cost_rupees===0?"free":`₹${step.cost_rupees}`} · {step.time_days} days{step.where?` · ${step.where}`:""}
                  </div>
                  {step.detail && <div className="text-[11px] text-white/45 mt-1">{step.detail}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* spoken answer */}
      <div className="rounded-xl p-4" style={{ border:`1px solid ${color}35`, background:`${color}0a` }}>
        <div className="text-[9px] tracking-[0.38em] uppercase mb-1" style={{ color, fontFamily:"'JetBrains Mono',monospace" }}>WHAT HE HEARS</div>
        <div className="text-[10px] text-white/28 mb-3">He has no screen. This is the entire product from his side.</div>
        <div className="text-[14px] leading-[1.8] text-white/85 mb-4">{result.spoken_text}</div>
        {audioSrc
          ? <audio controls autoPlay src={audioSrc} className="w-full" style={{ filter:"invert(0.9) hue-rotate(180deg)" }} />
          : <div className="text-[11px] text-amber-400/70" style={{ fontFamily:"'JetBrains Mono',monospace" }}>⚠ No audio — TTS unavailable. Text shown above.</div>}
      </div>
    </motion.div>
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

  const C = "#0df2a0"; // doc doctor color

  return (
    <div className="h-full overflow-y-auto px-10 py-8" style={{ scrollbarWidth:"none" }}>
      <div style={{ maxWidth:680, margin:"0 auto" }}>
        <div className="flex items-center gap-3 mb-2">
          <span className="text-[10px] tracking-[0.38em] uppercase" style={{ color:C, fontFamily:"'JetBrains Mono',monospace" }}>DOC DOCTOR</span>
        </div>
        <h2 className="text-[2rem] font-bold text-white/90 mb-2" style={{ letterSpacing:"-0.02em" }}>Check before you apply</h2>
        <p className="text-[13px] text-white/40 mb-8 leading-relaxed">
          A name spelled one way on an Aadhaar and another on a passbook is how applications die silently — months later, without a reason.
          Upload two or more documents and we check for mismatches now.
        </p>

        {/* upload zone */}
        <div onClick={() => inputRef.current?.click()}
          className="rounded-xl p-8 text-center cursor-pointer transition-all mb-5"
          style={{ border:`1.5px dashed ${files.length>0?C+"60":"rgba(255,255,255,0.1)"}`, background: files.length>0?`${C}07`:"rgba(255,255,255,0.02)" }}>
          <Upload className="w-6 h-6 mx-auto mb-3 text-white/30" />
          <div className="text-[13px] text-white/50">Click to upload document photos</div>
          <div className="text-[11px] text-white/25 mt-1" style={{ fontFamily:"'JetBrains Mono',monospace" }}>JPG · PNG · PDF — name as aadhaar.jpg, passbook.jpg etc.</div>
          <input ref={inputRef} type="file" multiple accept=".jpg,.jpeg,.png,.webp,.pdf" className="hidden"
            onChange={e => setFiles(Array.from(e.target.files ?? []))} />
        </div>

        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-5">
            {files.map((f,i) => (
              <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-lg text-[12px]"
                style={{ background:`${C}12`, border:`1px solid ${C}30`, color:C, fontFamily:"'JetBrains Mono',monospace" }}>
                <FileText className="w-3 h-3" />{f.name}
              </div>
            ))}
          </div>
        )}

        <button onClick={check} disabled={files.length<2||loading}
          className="flex items-center gap-2 rounded-xl text-[13px] font-bold transition-all disabled:opacity-30 disabled:cursor-not-allowed mb-6"
          style={{ background:C, color:"#000", padding:"11px 28px", boxShadow: files.length>=2&&!loading?`0 0 28px ${C}55`:"none" }}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
          {loading ? "Reading documents…" : "Run check"}
        </button>
        {files.length===1&&<div className="text-[12px] text-white/30 mb-4" style={{ fontFamily:"'JetBrains Mono',monospace" }}>Add one more document — the check is a comparison.</div>}

        {error && <div className="rounded-xl p-4 mb-4 text-[12px] text-red-400" style={{ background:"#ff000011", border:"1px solid #ff000033", fontFamily:"'JetBrains Mono',monospace" }}>{error}</div>}

        {report && (
          <motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}}>
            {/* summary banner */}
            <div className="rounded-xl p-4 mb-4 flex items-center gap-3"
              style={{ background: report.clear?"#00ff9412":"#ff000012", border:`1px solid ${report.clear?"#00ff9440":"#ff000040"}` }}>
              {report.clear
                ? <CheckCircle className="w-5 h-5 text-emerald-400 flex-shrink-0" />
                : <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" />}
              <div>
                <div className={`text-[13px] font-bold ${report.clear?"text-emerald-400":"text-red-400"}`}>{report.summary}</div>
                {!report.reading_is_reliable && <div className="text-[11px] text-amber-400/70 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>⚠ OCR used as fallback — readings may be less accurate</div>}
              </div>
            </div>

            {/* findings */}
            {report.findings.map((f,i) => (
              <div key={i} className="rounded-xl p-4 mb-3"
                style={{ background: f.severity==="blocker"?"#ff000010":"#f5a62310", border:`1px solid ${f.severity==="blocker"?"#ff000040":"#f5a62340"}` }}>
                <div className="flex items-start gap-2 mb-2">
                  <XCircle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color:f.severity==="blocker"?"#ff4560":"#f5a623" }} />
                  <div className="text-[13px] font-semibold text-white/85">{f.message}</div>
                </div>
                {Object.entries(f.values).length>0 && (
                  <div className="ml-6 flex flex-wrap gap-2 mb-2">
                    {Object.entries(f.values).map(([doc,name]) => (
                      <div key={doc} className="px-3 py-1.5 rounded-lg text-[11px]"
                        style={{ background:"rgba(255,255,255,0.05)", border:"1px solid rgba(255,255,255,0.1)", fontFamily:"'JetBrains Mono',monospace" }}>
                        <span className="text-white/35">{doc}: </span><span className="text-white/75">{name}</span>
                      </div>
                    ))}
                  </div>
                )}
                {f.consequence && <div className="ml-6 text-[11px] text-white/45 mb-1"><span className="text-white/30">What this costs: </span>{f.consequence}</div>}
                {f.fix && <div className="ml-6 text-[11px] text-emerald-400/70"><span className="text-white/30">Fix: </span>{f.fix}</div>}
              </div>
            ))}

            {/* what we read */}
            <div className="rounded-xl overflow-hidden" style={{ border:"1px solid rgba(255,255,255,0.08)" }}>
              <div className="px-4 py-2.5 text-[9px] tracking-[0.38em] uppercase text-white/25 border-b border-white/05" style={{ fontFamily:"'JetBrains Mono',monospace" }}>WHAT WE READ OFF EACH DOCUMENT</div>
              <div className="divide-y divide-white/05">
                {report.documents.map((d,i) => (
                  <div key={i} className="px-4 py-3 flex gap-4 flex-wrap text-[11px]">
                    <span className="text-white/55 font-bold min-w-[120px]">{d.label}</span>
                    <span style={{ fontFamily:"'JetBrains Mono',monospace", color:"rgba(255,255,255,0.5)" }}>{d.name ?? "—"}</span>
                    {d.dob && <span className="text-white/30" style={{ fontFamily:"'JetBrains Mono',monospace" }}>DOB {d.dob}</span>}
                    <span className="text-white/20 ml-auto" style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:"0.65rem" }}>{d.extraction_method}</span>
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

  const C = "#f5c842"; // ledger color

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
      setEntry("");
      fetchStatement();
    } catch(e) { setPostMsg("Failed to record entry"); }
    finally { setPosting(false); }
  };

  const maxEarned = statement ? Math.max(...statement.daily.map(d => d.earned ?? 0), 1) : 1;

  return (
    <div className="h-full overflow-y-auto px-10 py-8" style={{ scrollbarWidth:"none" }}>
      <div style={{ maxWidth:720, margin:"0 auto" }}>
        <div className="flex items-center gap-3 mb-2">
          <span className="text-[10px] tracking-[0.38em] uppercase" style={{ color:C, fontFamily:"'JetBrains Mono',monospace" }}>VOICE LEDGER</span>
        </div>
        <h2 className="text-[2rem] font-bold text-white/90 mb-2" style={{ letterSpacing:"-0.02em" }}>Trust Passport</h2>
        <p className="text-[13px] text-white/40 mb-6 leading-relaxed">
          Every evening the vendor speaks five seconds. Thirty of those become a cash-flow statement a loan officer can actually read.
        </p>

        {/* controls row */}
        <div className="flex gap-3 flex-wrap mb-6">
          <input value={userId} onChange={e => setUserId(e.target.value)}
            className="rounded-xl text-[12px] outline-none px-3 py-2"
            style={{ background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:"rgba(255,255,255,0.6)", fontFamily:"'JetBrains Mono',monospace", width:140 }}
            placeholder="user_id" />
          <button onClick={()=>fetchStatement()} disabled={loading}
            className="flex items-center gap-2 rounded-xl text-[12px] font-bold transition-all disabled:opacity-40"
            style={{ background:C, color:"#000", padding:"9px 18px" }}>
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <TrendingUp className="w-3.5 h-3.5"/>}
            Load statement
          </button>
          <button onClick={seed} disabled={seeding||loading}
            className="flex items-center gap-2 rounded-xl text-[12px] transition-all disabled:opacity-30"
            style={{ border:`1px solid ${C}40`, color:C, padding:"9px 18px", background:`${C}0a` }}>
            {seeding ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : <Coins className="w-3.5 h-3.5"/>}
            Seed 30 demo days
          </button>
        </div>

        {/* add entry */}
        <div className="rounded-xl p-4 mb-6" style={{ border:`1px solid ${C}20`, background:`${C}07` }}>
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
          {postMsg && <div className="mt-2 text-[11px] text-emerald-400" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{postMsg}</div>}
        </div>

        {error && <div className="rounded-xl p-3 mb-4 text-[12px] text-red-400" style={{ background:"#ff000011", border:"1px solid #ff000033", fontFamily:"'JetBrains Mono',monospace" }}>{error}</div>}

        {statement && (
          <motion.div initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} className="space-y-4">
            {/* summary cards */}
            <div className="grid grid-cols-3 gap-3">
              {[
                ["Total earned",   `₹${statement.total_earned.toLocaleString()}`],
                ["Net",            `₹${statement.net.toLocaleString()}`],
                ["Median / day",   `₹${statement.median_daily_earned.toLocaleString()}`],
              ].map(([k,v]) => (
                <div key={k} className="rounded-xl p-4 text-center" style={{ border:`1px solid ${C}25`, background:`${C}09` }}>
                  <div className="text-[22px] font-bold" style={{ color:C }}>{v}</div>
                  <div className="text-[10px] text-white/30 mt-0.5" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{k}</div>
                </div>
              ))}
            </div>

            {/* provenance + confidence */}
            <div className="rounded-xl p-4" style={{ border:`1px solid rgba(255,255,255,0.08)`, background:"rgba(255,255,255,0.02)" }}>
              <div className="flex gap-6 flex-wrap text-[11px] mb-3">
                {[
                  ["Period",       `${statement.period_start} → ${statement.period_end}`],
                  ["Days covered", `${statement.days_covered} / ${statement.days_in_period} (${Math.round(statement.coverage_pct*100)}%)`],
                  ["Corroborated", `${Math.round(statement.corroboration_pct*100)}% via UPI`],
                  ["Confidence",   statement.confidence.toUpperCase()],
                ].map(([k,v]) => (
                  <div key={k}>
                    <div className="text-white/25 text-[9px] tracking-widest uppercase" style={{ fontFamily:"'JetBrains Mono',monospace" }}>{k}</div>
                    <div className={`mt-0.5 font-semibold ${k==="Confidence"&&statement.confidence==="strong"?"text-emerald-400":k==="Confidence"&&statement.confidence==="indicative"?"text-amber-400":"text-white/65"}`}>{v}</div>
                  </div>
                ))}
              </div>
              {statement.caveats.map((c,i)=>(
                <div key={i} className="text-[11px] text-white/35 py-1 border-t border-white/04">⚠ {c}</div>
              ))}
            </div>

            {/* chart */}
            {statement.daily.length > 0 && (
              <div className="rounded-xl p-4" style={{ border:`1px solid ${C}20`, background:`${C}07` }}>
                <div className="text-[9px] tracking-[0.38em] uppercase mb-4" style={{ color:C, fontFamily:"'JetBrains Mono',monospace" }}>DAILY EARNINGS — {statement.daily.length} days</div>
                <div className="flex items-end gap-1" style={{ height:80 }}>
                  {statement.daily.map((day,i) => (
                    <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative" style={{ minWidth:0 }}>
                      <div className="w-full rounded-sm transition-all"
                        style={{ height:`${Math.round((day.earned/maxEarned)*72)+4}px`,
                          background: day.corroborated?`${C}cc`:`${C}55`,
                          border: day.corroborated?`1px solid ${C}`:"none" }} />
                      <div className="absolute bottom-full mb-1 text-[9px] rounded px-1.5 py-0.5 opacity-0 group-hover:opacity-100 pointer-events-none whitespace-nowrap z-10"
                        style={{ background:"rgba(0,0,0,0.85)", border:`1px solid ${C}30`, color:"rgba(255,255,255,0.8)", fontFamily:"'JetBrains Mono',monospace" }}>
                        {day.date}<br/>₹{day.earned.toLocaleString()}{day.spent?` · spent ₹${day.spent.toLocaleString()}`:""}{day.corroborated?" · UPI ✓":""}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="flex justify-between mt-1 text-[9px] text-white/20" style={{ fontFamily:"'JetBrains Mono',monospace" }}>
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

/* ─────────────── Neon right panel (unchanged) ─────────────── */
function NeonPanel({ statuses, active, prog }: { statuses: Status[]; active: number; prog: number[] }) {
  const activeColor = active >= 0 ? STAGES[active].color : "transparent";
  const bgY = active===0?"14%":active===1?"50%":active===2?"86%":"50%";
  return (
    <div className="w-full h-full relative">
      <div className="absolute inset-0 transition-all duration-1000 pointer-events-none"
        style={{ background: active>=0?`radial-gradient(ellipse 80% 32% at 50% ${bgY}, ${activeColor}1e 0%, transparent 72%)`:"transparent" }} />
      {active>=0 && (
        <motion.div key={active} className="absolute pointer-events-none"
          style={{ left:"50%", top:bgY, transform:"translate(-50%,-50%)", width:160, height:160, borderRadius:"50%", border:`1px solid ${activeColor}35` }}
          animate={{ scale:[1,1.25,1], opacity:[0.4,0.08,0.4] }}
          transition={{ duration:2.4, repeat:Infinity, ease:"easeInOut" }} />
      )}
      {active>=0 && (
        <motion.div className="absolute left-0 right-0 pointer-events-none"
          style={{ height:1, background:`linear-gradient(to right, transparent 0%, ${activeColor}30 35%, ${activeColor}55 50%, ${activeColor}30 65%, transparent 100%)` }}
          animate={{ top:["0%","100%"] }}
          transition={{ duration:5, repeat:Infinity, ease:"linear", repeatDelay:1 }} />
      )}
      <svg viewBox="0 0 400 900" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 w-full h-full">
        <defs>
          <filter id="f-xl" x="-120%" y="-20%" width="340%" height="140%"><feGaussianBlur stdDeviation="13" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="f-md" x="-60%" y="-10%" width="220%" height="120%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        {PATHS.map((d,i)=>(<path key={`ghost-${i}`} d={d} fill="none" stroke={STAGES[i].color} strokeWidth={1} opacity={0.07}/>))}
        {PATHS.map((d,i)=>(<NeonPath key={i} d={d} color={STAGES[i].color} progress={prog[i]} isProcessing={statuses[i]==="processing"}/>))}
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
  const pt = { duration:1.5, ease:"easeOut" as const };
  const pulse = { repeat:Infinity, duration:1.8, ease:"easeInOut" as const };
  return (
    <>
      <motion.path d={d} fill="none" stroke={color} strokeWidth={32} strokeLinecap="round" filter="url(#f-xl)"
        initial={{ pathLength:0, opacity:0 }}
        animate={{ pathLength:progress, opacity: isProcessing?[0.12,0.38,0.12]:progress>0?0.22:0 }}
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
