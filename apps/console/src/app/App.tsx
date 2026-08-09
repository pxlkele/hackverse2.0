import { useState, useRef } from "react";
import { motion } from "motion/react";
import {
  Mic,
  Database,
  Volume2,
  Send,
  RotateCcw,
  CheckCircle2,
  Loader2,
  Activity,
} from "lucide-react";

const pause = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Shapes returned by POST /api/reason. */
type Rule = {
  passed: boolean | null;
  label: string;
  expected: string;
  actual: string;
  citation: string;
  quote: string;
};
type LadderRung = {
  order: number;
  action: string;
  cost_rupees: number;
  time_days: number;
  where: string;
};
type Decision = {
  scheme_name: string;
  status: string;
  ladder: LadderRung[] | null;
  total_cost_rupees: number | null;
  total_time_days: number | null;
};
type ReasonResponse = {
  profile: Record<string, unknown>;
  steps: Array<Record<string, any>>;
  decisions: Decision[];
  spoken_text: string;
  audio_path: string | null;
  trace_fingerprint: string;
  timings_ms: Record<string, number>;
};

const pad = (s: string, n: number) => s.padEnd(n).slice(0, n);

/** What Granite heard. Only fields the person actually stated. */
function formatProfile(r: ReasonResponse): string {
  const p = r.profile;
  const rows: [string, unknown][] = [
    ["occupation", p.occupation],
    ["category", p.occupation_category],
    ["age", p.age],
    ["daily income", p.daily_income ? `Rs ${p.daily_income}` : null],
    ["years trading", p.years_in_business],
    ["location", [p.city, p.state].filter(Boolean).join(", ") || null],
    ["documents", (p.documents as string[])?.join(", ") || "none stated"],
  ];
  const body = rows
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${pad(k, 14)}${v}`)
    .join("\n");
  const derived = (p.derived_fields as string[]) ?? [];
  return derived.length
    ? `${body}\n\nderived (not stated by the user):\n${derived.map((d) => `  ${d}`).join("\n")}`
    : body;
}

/** Every rule that fired, with the document and page behind it. */
function formatRules(r: ReasonResponse): string {
  const blocks: string[] = [];
  let scheme = "";
  for (const step of r.steps) {
    if (step.kind === "scheme") {
      scheme = `${step.label}  —  ${step.detail}`;
      blocks.push(`\n${scheme}`);
    } else if (step.kind === "rule") {
      const mark = step.passed === true ? "PASS" : step.passed === false ? "FAIL" : " ?? ";
      blocks.push(`  [${mark}] ${pad(step.label, 46)} ${step.citation}`);
    }
  }
  return blocks.join("\n").trim();
}

/** The decision, the path out of it, and what it really cost in time. */
function formatOutcome(r: ReasonResponse): string {
  const lines: string[] = [];
  for (const d of r.decisions) {
    lines.push(`${pad(d.scheme_name, 30)}${d.status.toUpperCase()}`);
    if (d.ladder) {
      lines.push(
        `   path: ${d.ladder.length} steps, Rs ${d.total_cost_rupees ?? 0}, ${d.total_time_days} days`,
      );
      for (const rung of d.ladder) {
        const cost = rung.cost_rupees === 0 ? "free" : `Rs ${rung.cost_rupees}`;
        lines.push(`     ${rung.order}. ${rung.action}`);
        lines.push(`        ${cost} · ${rung.time_days}d · ${rung.where}`);
      }
    }
  }
  const t = r.timings_ms;
  const total = Object.values(t).reduce((a, b) => a + b, 0);
  lines.push("");
  lines.push(`trace       ${r.trace_fingerprint}   (same input, same trace, always)`);
  lines.push(
    `latency     ${Math.round(total)}ms  (` +
      Object.entries(t)
        .map(([k, v]) => `${k.replace("_ms", "")} ${Math.round(v)}`)
        .join(" / ") +
      ")",
  );
  return lines.join("\n");
}

type Status = "idle" | "processing" | "complete";

const STAGES = [
  {
    num: "01",
    title: "Input & Understanding",
    sub: "ASR → Profile",
    idle: "Awaiting input…",
    running: "Transcribing and profiling…",
    done: "Profile extracted",
    Icon: Mic,
    color: "#00f5ff",
    dataLabel: "EXTRACTED PROFILE",
  },
  {
    num: "02",
    title: "Retrieval & Matching",
    sub: "RAG → Rules",
    idle: "Waiting for profile…",
    running: "Querying knowledge base…",
    done: "Rules matched",
    Icon: Database,
    color: "#a855f7",
    dataLabel: "MATCHED RULES",
  },
  {
    num: "03",
    title: "Response & Outcome",
    sub: "Decision → TTS",
    idle: "Awaiting retrieval…",
    running: "Synthesizing response…",
    done: "Response ready",
    Icon: Volume2,
    color: "#f43df7",
    dataLabel: "PIPELINE OUTCOME",
  },
] as const;

// Three woven neon paths flowing top→bottom through a 400×900 viewBox
const PATHS = [
  "M 160 0 C 30 90 330 180 160 300 C 30 420 330 510 160 630 C 30 750 330 840 160 900",
  "M 240 0 C 370 90 70 180 240 300 C 370 420 70 510 240 630 C 370 750 70 840 240 900",
  "M 200 -40 C 50 60 360 150 200 260 C 50 370 360 460 200 570 C 50 680 360 760 200 900",
];

export default function App() {
  const [input, setInput] = useState("");
  const [statuses, setStatuses] = useState<Status[]>(["idle", "idle", "idle"]);
  const [active, setActive] = useState(-1);
  const [isRunning, setIsRunning] = useState(false);
  const [stageData, setStageData] = useState(["", "", ""]);
  const [spoken, setSpoken] = useState("");
  const [audio, setAudio] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [lang, setLang] = useState("hi");
  const abortRef = useRef(false);

  const r0 = useRef<HTMLDivElement>(null);
  const r1 = useRef<HTMLDivElement>(null);
  const r2 = useRef<HTMLDivElement>(null);
  const refs = [r0, r1, r2];

  const scrollTo = (i: number) =>
    refs[i].current?.scrollIntoView({ behavior: "smooth", block: "start" });

  const run = async () => {
    if (!input.trim() || isRunning) return;
    abortRef.current = false;
    setIsRunning(true);
    setStageData(["", "", ""]);
    setError("");
    setAudio(null);

    // Stage 0 — Input & Understanding
    setStatuses(["processing", "idle", "idle"]);
    setActive(0);
    scrollTo(0);

    let result: ReasonResponse;
    try {
      const response = await fetch("/api/reason", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: input.trim(), language: lang }),
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      result = await response.json();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not reach the Setu API on :8000",
      );
      setStatuses(["idle", "idle", "idle"]);
      setActive(-1);
      setIsRunning(false);
      return;
    }
    if (abortRef.current) return;

    // The API answers in one call. The reveal below is paced so a human can
    // read it — but every line is a real evaluation, not a re-enactment.
    setStageData([formatProfile(result), "", ""]);
    setStatuses(["complete", "processing", "idle"]);
    setActive(1);
    setTimeout(() => scrollTo(1), 420);
    await pause(900);
    if (abortRef.current) return;

    // Stage 1 — Retrieval & Matching: the rules that actually fired, each with
    // the government document and page it came from.
    setStageData((p) => [p[0], formatRules(result), ""]);
    setStatuses(["complete", "complete", "processing"]);
    setActive(2);
    setTimeout(() => scrollTo(2), 420);
    await pause(900);
    if (abortRef.current) return;

    // Stage 2 — Response & Outcome
    setStageData((p) => [p[0], p[1], formatOutcome(result)]);
    setSpoken(result.spoken_text);
    if (result.audio_path) setAudio(`/api/audio?path=${encodeURIComponent(result.audio_path)}`);
    setStatuses(["complete", "complete", "complete"]);
    setIsRunning(false);
  };

  const reset = () => {
    abortRef.current = true;
    setStatuses(["idle", "idle", "idle"]);
    setActive(-1);
    setIsRunning(false);
    setStageData(["", "", ""]);
    setInput("");
    setSpoken("");
    setAudio(null);
    setError("");
    scrollTo(0);
  };

  const allDone = statuses.every((s) => s === "complete");
  const prog = statuses.map((s) =>
    s === "complete" ? 1 : s === "processing" ? 0.5 : 0
  );

  return (
    <div
      className="w-full bg-black overflow-hidden"
      style={{ height: "100dvh", fontFamily: "'Oxanium', sans-serif" }}
    >
      {/* ── Header ── */}
      <div className="absolute top-0 left-0 right-0 z-30 flex items-center justify-between px-10 py-5 pointer-events-none">
        <div className="flex items-center gap-3">
          <Activity className="w-3.5 h-3.5" style={{ color: "rgba(255,255,255,0.18)" }} />
          <span
            className="text-[10px] tracking-[0.32em] uppercase"
            style={{ color: "rgba(255,255,255,0.18)", fontFamily: "'JetBrains Mono', monospace" }}
          >
            AI PIPELINE MONITOR
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          {STAGES.map((s, i) => (
            <div
              key={i}
              className="rounded-full transition-all duration-500"
              style={{
                width: statuses[i] === "processing" ? "10px" : "6px",
                height: statuses[i] === "processing" ? "10px" : "6px",
                background:
                  statuses[i] === "idle" ? "rgba(255,255,255,0.12)" : s.color,
                boxShadow:
                  statuses[i] !== "idle" ? `0 0 10px ${s.color}90` : "none",
              }}
            />
          ))}
        </div>
      </div>

      <div className="flex h-full">
        {/* ── Left: snap-scroll carousel ── */}
        <div
          className="h-full overflow-y-scroll snap-y snap-mandatory"
          style={{ width: "58%", scrollbarWidth: "none" }}
        >
          {STAGES.map((stage, i) => (
            <div
              key={i}
              ref={refs[i]}
              className="snap-start relative flex flex-col justify-center"
              style={{
                height: "100dvh",
                paddingLeft: "clamp(2.5rem, 7vw, 4rem)",
                paddingRight: "2rem",
              }}
            >
              {/* Vertical connector to next stage */}
              {i < 2 && (
                <div
                  className="absolute bottom-0 transition-all duration-700"
                  style={{
                    left: "clamp(2.5rem, 7vw, 4rem)",
                    width: "1px",
                    height: "80px",
                    background: `linear-gradient(to bottom, ${stage.color}50, transparent)`,
                    opacity: statuses[i] === "complete" ? 1 : 0.15,
                  }}
                />
              )}

              <div style={{ maxWidth: "490px" }}>
                {/* Stage meta label */}
                <div className="flex items-center gap-3 mb-7">
                  <span
                    className="text-[10px] tracking-[0.38em] uppercase"
                    style={{
                      color: stage.color,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {stage.num}
                  </span>
                  <div
                    className="h-px w-6"
                    style={{ background: stage.color, opacity: 0.35 }}
                  />
                  <span
                    className="text-[10px] tracking-[0.25em] uppercase"
                    style={{
                      color: "rgba(255,255,255,0.2)",
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {stage.sub}
                  </span>
                </div>

                {/* Title */}
                <h2
                  className="font-bold mb-3 transition-colors duration-500"
                  style={{
                    fontSize: "clamp(1.9rem, 3.8vw, 2.8rem)",
                    lineHeight: 1.05,
                    letterSpacing: "-0.025em",
                    color:
                      statuses[i] === "idle"
                        ? "rgba(255,255,255,0.16)"
                        : "#ffffff",
                  }}
                >
                  {stage.title}
                </h2>

                {/* Status line */}
                <div className="flex items-center gap-2.5 mb-8">
                  {statuses[i] === "processing" ? (
                    <Loader2
                      className="w-3 h-3 animate-spin"
                      style={{ color: stage.color }}
                    />
                  ) : statuses[i] === "complete" ? (
                    <CheckCircle2 className="w-3 h-3" style={{ color: stage.color }} />
                  ) : (
                    <stage.Icon
                      className="w-3 h-3"
                      style={{ color: "rgba(255,255,255,0.16)" }}
                    />
                  )}
                  <span
                    className="text-[12px] transition-colors duration-300"
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      color:
                        statuses[i] === "processing"
                          ? stage.color
                          : statuses[i] === "complete"
                          ? "rgba(255,255,255,0.4)"
                          : "rgba(255,255,255,0.18)",
                    }}
                  >
                    {statuses[i] === "idle"
                      ? stage.idle
                      : statuses[i] === "processing"
                      ? stage.running
                      : stage.done}
                  </span>
                </div>

                {/* Input textarea (stage 0 only) */}
                {i === 0 && (
                  <div className="space-y-3.5">
                    <textarea
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          run();
                        }
                      }}
                      disabled={isRunning}
                      rows={4}
                      placeholder="Main pani puri ka thela chalata hoon…"
                      className="w-full rounded-xl text-[13px] resize-none outline-none transition-all duration-300"
                      style={{
                        background: "rgba(255,255,255,0.04)",
                        border: `1px solid ${
                          statuses[0] === "processing"
                            ? stage.color + "55"
                            : "rgba(255,255,255,0.08)"
                        }`,
                        padding: "13px 15px",
                        color: "rgba(255,255,255,0.65)",
                        fontFamily: "'JetBrains Mono', monospace",
                        boxShadow:
                          statuses[0] === "processing"
                            ? `0 0 30px ${stage.color}14, inset 0 0 20px ${stage.color}07`
                            : "none",
                      }}
                    />
                    <div className="flex gap-3 items-center">
                      <select
                        value={lang}
                        onChange={(e) => setLang(e.target.value)}
                        disabled={isRunning}
                        className="rounded-xl text-[12px] outline-none"
                        style={{
                          background: "rgba(255,255,255,0.04)",
                          border: "1px solid rgba(255,255,255,0.08)",
                          padding: "10px 12px",
                          color: "rgba(255,255,255,0.6)",
                          fontFamily: "'JetBrains Mono', monospace",
                        }}
                      >
                        <option value="hi">reply in Hindi</option>
                        <option value="mr">Marathi</option>
                        <option value="kn">Kannada</option>
                        <option value="ta">Tamil</option>
                        <option value="en">English</option>
                      </select>
                      <button
                        onClick={run}
                        disabled={!input.trim() || isRunning}
                        className="flex items-center gap-2 rounded-xl text-[13px] font-bold transition-all duration-300 disabled:opacity-20 disabled:cursor-not-allowed"
                        style={{
                          background: stage.color,
                          color: "#000",
                          padding: "10px 22px",
                          boxShadow:
                            input.trim() && !isRunning
                              ? `0 0 28px ${stage.color}55, 0 0 56px ${stage.color}22`
                              : "none",
                        }}
                      >
                        <Send className="w-3 h-3" />
                        Run Pipeline
                      </button>

                      {error && (
                        <div
                          className="text-[12px] rounded-xl flex items-center"
                          style={{
                            border: "1px solid #f4433d55",
                            background: "#f4433d11",
                            padding: "10px 16px",
                            color: "#ff8a85",
                            fontFamily: "'JetBrains Mono', monospace",
                          }}
                        >
                          {error} — is uvicorn running on :8000?
                        </div>
                      )}

                      {allDone && (
                        <motion.button
                          initial={{ opacity: 0, x: -6 }}
                          animate={{ opacity: 1, x: 0 }}
                          onClick={reset}
                          className="flex items-center gap-2 rounded-xl text-[13px] font-semibold transition-colors"
                          style={{
                            border: "1px solid rgba(255,255,255,0.1)",
                            padding: "10px 22px",
                            color: "rgba(255,255,255,0.38)",
                          }}
                          onMouseEnter={(e) =>
                            (e.currentTarget.style.color = "rgba(255,255,255,0.7)")
                          }
                          onMouseLeave={(e) =>
                            (e.currentTarget.style.color = "rgba(255,255,255,0.38)")
                          }
                        >
                          <RotateCcw className="w-3 h-3" />
                          Reset
                        </motion.button>
                      )}
                    </div>
                  </div>
                )}

                {/* Data output */}
                {stageData[i] && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5 }}
                    className="mt-5 rounded-xl p-4"
                    style={{
                      background: `${stage.color}09`,
                      border: `1px solid ${stage.color}25`,
                    }}
                  >
                    <div
                      className="text-[9px] tracking-[0.38em] uppercase mb-3"
                      style={{
                        color: stage.color,
                        fontFamily: "'JetBrains Mono', monospace",
                      }}
                    >
                      {stage.dataLabel}
                    </div>
                    <pre
                      className="text-[11px] whitespace-pre leading-[1.85]"
                      style={{
                        color: "rgba(255,255,255,0.42)",
                        fontFamily: "'JetBrains Mono', monospace",
                      }}
                    >
                      {stageData[i]}
                    </pre>
                  </motion.div>
                )}

                {/* Stage 2 closes on what the vendor actually receives. He has
                    no screen — this console is the operator's view, and the
                    audio below is the entire product from his side. */}
                {i === 2 && spoken && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: 0.2 }}
                    className="mt-5 rounded-xl p-5"
                    style={{
                      background: `${stage.color}0d`,
                      border: `1px solid ${stage.color}40`,
                    }}
                  >
                    <div
                      className="text-[9px] tracking-[0.38em] uppercase mb-1"
                      style={{ color: stage.color, fontFamily: "'JetBrains Mono', monospace" }}
                    >
                      WHAT HE HEARS
                    </div>
                    <div
                      className="text-[10px] mb-4"
                      style={{ color: "rgba(255,255,255,0.3)" }}
                    >
                      He has no screen. This is the whole product from his side.
                    </div>
                    <div
                      className="text-[15px] leading-[1.8] mb-4"
                      style={{ color: "rgba(255,255,255,0.88)" }}
                    >
                      {spoken}
                    </div>
                    {audio ? (
                      <audio controls autoPlay src={audio} className="w-full" />
                    ) : (
                      <div className="text-[11px]" style={{ color: "#d9a441" }}>
                        No audio for this line — text-to-speech needs the network
                        for text it has not spoken before. The answer stands above.
                      </div>
                    )}
                  </motion.div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* ── Right: neon visualization ── */}
        <div className="h-full relative overflow-hidden" style={{ flex: 1 }}>
          <NeonPanel statuses={statuses} active={active} prog={prog} />
        </div>
      </div>
    </div>
  );
}

/* ─────────────── Neon right panel ─────────────── */

function NeonPanel({
  statuses,
  active,
  prog,
}: {
  statuses: Status[];
  active: number;
  prog: number[];
}) {
  const activeColor = active >= 0 ? STAGES[active].color : "transparent";
  const bgY =
    active === 0 ? "14%" : active === 1 ? "50%" : active === 2 ? "86%" : "50%";

  return (
    <div className="w-full h-full relative">
      {/* Ambient background pulse */}
      <div
        className="absolute inset-0 transition-all duration-1000 pointer-events-none"
        style={{
          background:
            active >= 0
              ? `radial-gradient(ellipse 80% 32% at 50% ${bgY}, ${activeColor}1e 0%, transparent 72%)`
              : "transparent",
        }}
      />

      {/* Pulsing ring at active stage position */}
      {active >= 0 && (
        <motion.div
          key={active}
          className="absolute pointer-events-none"
          style={{
            left: "50%",
            top: bgY,
            transform: "translate(-50%, -50%)",
            width: 160,
            height: 160,
            borderRadius: "50%",
            border: `1px solid ${activeColor}35`,
          }}
          animate={{
            scale: [1, 1.25, 1],
            opacity: [0.4, 0.08, 0.4],
          }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
        />
      )}

      {/* Scanning sweep line */}
      {active >= 0 && (
        <motion.div
          className="absolute left-0 right-0 pointer-events-none"
          style={{
            height: "1px",
            background: `linear-gradient(to right, transparent 0%, ${activeColor}30 35%, ${activeColor}55 50%, ${activeColor}30 65%, transparent 100%)`,
          }}
          animate={{ top: ["0%", "100%"] }}
          transition={{ duration: 5, repeat: Infinity, ease: "linear", repeatDelay: 1 }}
        />
      )}

      {/* SVG — the twisted neon paths */}
      <svg
        viewBox="0 0 400 900"
        preserveAspectRatio="xMidYMid slice"
        className="absolute inset-0 w-full h-full"
      >
        <defs>
          <filter id="f-xl" x="-120%" y="-20%" width="340%" height="140%">
            <feGaussianBlur stdDeviation="13" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="f-md" x="-60%" y="-10%" width="220%" height="120%">
            <feGaussianBlur stdDeviation="5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Ghost paths — always dim */}
        {PATHS.map((d, i) => (
          <path
            key={`ghost-${i}`}
            d={d}
            fill="none"
            stroke={STAGES[i].color}
            strokeWidth={1}
            opacity={0.07}
          />
        ))}

        {/* Live animated paths */}
        {PATHS.map((d, i) => (
          <NeonPath
            key={i}
            d={d}
            color={STAGES[i].color}
            progress={prog[i]}
            isProcessing={statuses[i] === "processing"}
          />
        ))}
      </svg>

      {/* Stage labels — right edge */}
      <div className="absolute right-5 inset-y-0 flex flex-col justify-around py-20 pointer-events-none">
        {STAGES.map((s, i) => (
          <div
            key={i}
            className="text-right transition-all duration-500"
            style={{ opacity: statuses[i] === "idle" ? 0.12 : 1 }}
          >
            <div
              className="text-[9px] tracking-[0.32em] uppercase mb-0.5"
              style={{ color: s.color, fontFamily: "'JetBrains Mono', monospace" }}
            >
              {s.num}
            </div>
            <div
              className="text-[10px]"
              style={{
                color: "rgba(255,255,255,0.35)",
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              {s.sub}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─────────────── Single neon SVG path ─────────────── */

function NeonPath({
  d,
  color,
  progress,
  isProcessing,
}: {
  d: string;
  color: string;
  progress: number;
  isProcessing: boolean;
}) {
  const pathTransition = { duration: 1.5, ease: "easeOut" as const };
  const pulseTransition = {
    repeat: Infinity,
    duration: 1.8,
    ease: "easeInOut" as const,
  };

  return (
    <>
      {/* Wide halo — outermost glow */}
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={32}
        strokeLinecap="round"
        filter="url(#f-xl)"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{
          pathLength: progress,
          opacity: isProcessing
            ? [0.12, 0.38, 0.12]
            : progress > 0
            ? 0.22
            : 0,
        }}
        transition={{
          pathLength: pathTransition,
          opacity: isProcessing ? pulseTransition : { duration: 0.7 },
        }}
      />

      {/* Medium glow — main neon body */}
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={7}
        strokeLinecap="round"
        filter="url(#f-md)"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{
          pathLength: progress,
          opacity: isProcessing
            ? [0.45, 0.95, 0.45]
            : progress > 0
            ? 0.65
            : 0,
        }}
        transition={{
          pathLength: pathTransition,
          opacity: isProcessing ? pulseTransition : { duration: 0.6 },
        }}
      />

      {/* Crisp core line */}
      <motion.path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{
          pathLength: progress,
          opacity: isProcessing ? [0.8, 1, 0.8] : progress > 0 ? 1 : 0,
        }}
        transition={{
          pathLength: pathTransition,
          opacity: isProcessing ? { ...pulseTransition, duration: 1.8 } : { duration: 0.3 },
        }}
      />
    </>
  );
}
