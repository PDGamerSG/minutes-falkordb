"use client";

import { useState, type CSSProperties } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Bot,
  Check,
  CheckCheck,
  Clock3,
  FileText,
  GitBranch,
  Layers,
  Mail,
  MessageSquare,
  Mic,
  Network,
  Plus,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import { MemorySculpture } from "@/components/memory/MemorySculpture";
import { MemoryMark } from "./CompanyMap";

export function ContextGap() {
  return (
    <section className="m-context-section m-container" id="inside-minutes">
      <div className="m-context-intro">
        <span className="m-eyebrow">A familiar problem</span>
        <h2>
          The work moves on.
          <br />
          The context gets left behind.
        </h2>
        <p>
          It’s in yesterday’s meeting. Somewhere in that email. In a decision
          that changed three times. Bring the pieces back together.
        </p>
      </div>
      <div className="m-gap-grid">
        <article>
          <div className="m-gap-art m-paper-art" aria-hidden="true">
            <span>
              <Mail size={18} />
              <i />
              <i />
            </span>
            <span>
              <Mic size={18} />
              <i />
              <i />
            </span>
            <span>
              <MessageSquare size={18} />
              <i />
              <i />
            </span>
            <div className="m-art-caption">“Where did we land on this?”</div>
          </div>
          <h3>Scattered conversations.</h3>
          <p>
            The meeting ends. The important details disappear into a pile of
            tabs.
          </p>
          <span>
            <Layers size={14} /> One connected source library
          </span>
        </article>
        <article>
          <div className="m-gap-art m-date-art" aria-hidden="true">
            <div>
              <s>24</s>
              <ArrowRight size={20} />
              <s>25</s>
              <ArrowRight size={20} />
              <strong>28</strong>
            </div>
            <div className="m-art-caption">
              “Wait, which date is the latest?”
            </div>
          </div>
          <h3>Decisions without a trail.</h3>
          <p>
            A new plan replaces the old one. The reason for the change gets
            lost.
          </p>
          <span>
            <Clock3 size={14} /> History that stays with the decision
          </span>
        </article>
        <article>
          <div className="m-gap-art m-block-art" aria-hidden="true">
            <div>
              {Array.from({ length: 35 }, (_, i) => (
                <i
                  key={i}
                  style={
                    {
                      "--i": i,
                      "--delay": `${(i % 7) * 30}ms`,
                    } as CSSProperties
                  }
                />
              ))}
            </div>
            <div className="m-art-caption">
              “Does everyone have the full picture?”
            </div>
          </div>
          <h3>A team out of sync.</h3>
          <p>
            People and agents start from different versions of the same story.
          </p>
          <span>
            <Network size={14} /> A shared memory to work from
          </span>
        </article>
      </div>
    </section>
  );
}

const history = [
  {
    label: "The first commitment",
    day: "24",
    source: "Product kickoff",
    text: "The team sets an initial target for the UPI flow. This is what everyone knows at the start.",
    state: "Original decision",
  },
  {
    label: "The plan changes",
    day: "25",
    source: "Payments follow-up",
    text: "A follow-up revises the deadline. The earlier commitment remains connected to the updated plan.",
    state: "Revised decision",
  },
  {
    label: "The current picture",
    day: "28",
    source: "Latest update",
    text: "The date moves again. Follow the complete chain to understand what is current and what changed.",
    state: "Current decision",
  },
];
export function HistorySection() {
  const [index, setIndex] = useState(2);
  const item = history[index];
  return (
    <section className="m-history-section">
      <div className="m-container m-split">
        <div className="m-feature-copy">
          <span className="m-eyebrow">
            <Clock3 size={14} /> A memory with a timeline
          </span>
          <h2>
            Things change.
            <br />
            The why stays.
          </h2>
          <p>
            “What did we know then?” is a different question from “What do we
            know now?” Minutes makes room for both.
          </p>
          <ul>
            <li>
              <Check size={15} /> Revisit an earlier version of a decision
            </li>
            <li>
              <Check size={15} /> Follow the source of every update
            </li>
            <li>
              <Check size={15} /> See which work still relies on an old plan
            </li>
          </ul>
          <a href="#how-it-works" className="m-inline-link">
            Follow a decision <ArrowUpRight size={15} />
          </a>
        </div>
        <div className="m-history-demo">
          <div className="m-history-top">
            <span>
              <GitBranch size={14} /> UPI release date
            </span>
            <small>Illustrative history</small>
          </div>
          <div className="m-history-card" key={index}>
            <div>
              <span>{item.label}</span>
              <span className="m-status blue">{item.state}</span>
            </div>
            <p className="m-calendar">
              <span>September</span>
              <strong>{item.day}</strong>
            </p>
            <p>{item.text}</p>
            <span className="m-history-source">
              <FileText size={13} />
              {item.source}
              <CheckCheck size={14} />
            </span>
          </div>
          <div className="m-history-controls">
            <label htmlFor="memory-history">
              Move through the story <span>{index + 1} / 3</span>
            </label>
            <input
              id="memory-history"
              aria-valuetext={`${item.label}: September ${item.day}`}
              type="range"
              min="0"
              max="2"
              step="1"
              value={index}
              onChange={(e) => setIndex(Number(e.target.value))}
            />
            <div>
              {history.map((s, i) => (
                <button
                  key={s.day}
                  onClick={() => setIndex(i)}
                  aria-pressed={i === index}
                >
                  Sep {s.day}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

const answers = [
  {
    role: "For product",
    icon: Layers,
    question: "Why did the release date move?",
    answer: (
      <>
        The UPI flow is now due <strong>September 28</strong>. The original
        September 24 commitment changed after sandbox access was delayed. The
        release handoff still needs a review against the current date.
      </>
    ),
    sources: [
      {
        title: "Product kickoff",
        quote:
          "Let’s target September 24 for the UPI flow. We need sandbox access before we can finish testing.",
      },
      {
        title: "Payments follow-up",
        quote:
          "Sandbox access is delayed. Move the UPI commitment to September 25.",
      },
      {
        title: "Release update",
        quote:
          "Move the UPI flow to September 28. Keep the release handoff in sync.",
      },
    ],
  },
  {
    role: "For engineering",
    icon: GitBranch,
    question: "Which navigation decision is current?",
    answer: (
      <>
        The team moved from a <strong>bottom tab bar to a side drawer</strong>.
        The earlier choice remains in the history. The navigation accessibility
        review is connected to the updated decision.
      </>
    ),
    sources: [
      {
        title: "Navigation review",
        quote: "We started with a bottom tab bar for the app shell.",
      },
      {
        title: "Design follow-up",
        quote:
          "Use the side drawer for the current navigation direction. Revisit the accessibility review against that decision.",
      },
    ],
  },
  {
    role: "For team leads",
    icon: Users,
    question: "Who needs to act on this change?",
    answer: (
      <>
        <strong>Rahul owns the release handoff</strong> in this example. Its
        dependency still references the earlier date, so he has the context to
        review the plan. Priya owns the release decision.
      </>
    ),
    sources: [
      {
        title: "Work dependency",
        quote:
          "The release handoff depends on the UPI date. It still references the September 24 commitment.",
      },
      {
        title: "Release handoff",
        quote:
          "Rahul will own the handoff. Keep the release date tied to the latest commitment from Priya.",
      },
    ],
  },
];
export function AnswersSection({ workspaceHref }: { workspaceHref: string }) {
  const [active, setActive] = useState(0);
  const [source, setSource] = useState<number | null>(null);
  const item = answers[active];
  return (
    <section className="m-answer-section m-container" id="answers">
      <div className="m-section-heading">
        <div>
          <span className="m-eyebrow">
            <MessageSquare size={14} /> Ask the company memory
          </span>
          <h2>
            Less catching up.
            <br />
            More getting somewhere.
          </h2>
        </div>
        <p>
          The same connected context, through your lens. Ask a useful question
          and follow the answer back to where it began.
        </p>
      </div>
      <div className="m-answer-layout">
        <div className="m-questions">
          <span>One memory. Different perspectives.</span>
          {answers.map(({ role, icon: Icon, question }, i) => (
            <button
              key={role}
              onClick={() => {
                setActive(i);
                setSource(null);
              }}
              aria-pressed={i === active}
            >
              <span>
                <Icon size={16} />
                {role}
              </span>
              <strong>{question}</strong>
              <ArrowUpRight size={17} />
            </button>
          ))}
          <a
            className="m-inline-link"
            href={
              workspaceHref.startsWith("#")
                ? workspaceHref
                : `${workspaceHref}/chat?q=${encodeURIComponent(item.question)}`
            }
          >
            Ask in your workspace <ArrowRight size={15} />
          </a>
        </div>
        <div className="m-answer-card">
          <div className="m-answer-top">
            <MemoryMark />
            <strong>Ask Minutes</strong>
            <span>Illustrative answer</span>
          </div>
          <div className="m-question-bubble" key={`q-${active}`}>
            {item.question}
          </div>
          <div className="m-answer-response" key={active} aria-live="polite">
            <span className="m-answer-spark">
              <Sparkles size={19} />
            </span>
            <p>{item.answer}</p>
            <div className="m-citations">
              {item.sources.map((s, i) => (
                <button
                  key={s.title}
                  onClick={() => setSource(source === i ? null : i)}
                  aria-expanded={source === i}
                >
                  <span>{i + 1}</span>
                  {s.title}
                  <ArrowUpRight size={11} />
                </button>
              ))}
            </div>
            <div className="m-answer-evidence">
              {source !== null ? (
                <blockquote>
                  <strong>{item.sources[source].title}</strong>“
                  {item.sources[source].quote}”
                  <small>Illustrative source excerpt</small>
                </blockquote>
              ) : (
                <span>
                  <ShieldCheck size={13} /> Open a source to see the supporting
                  context.
                </span>
              )}
            </div>
          </div>
          <div className="m-answer-bottom">
            <Network size={14} />
            <span>Conversations → decisions → people → work</span>
          </div>
        </div>
      </div>
    </section>
  );
}

const agentSteps = [
  {
    title: "A change comes in",
    detail: "A new source updates the release date.",
    icon: Mail,
  },
  {
    title: "The context comes together",
    detail: "The prior decision, dependency, and owner are connected.",
    icon: Network,
  },
  {
    title: "A follow-up takes shape",
    detail: "A draft includes the change and its source.",
    icon: Bot,
  },
  {
    title: "A person makes the call",
    detail: "The owner reviews the draft before acting.",
    icon: ShieldCheck,
  },
];
export function AgentSection({ workspaceHref }: { workspaceHref: string }) {
  const [step, setStep] = useState(0);
  return (
    <section className="m-agent-section">
      <div className="m-container m-split">
        <div className="m-feature-copy">
          <span className="m-eyebrow">
            <Bot size={14} /> People + agents
          </span>
          <h2>
            A shared starting point.
            <br />A better next step.
          </h2>
          <p>
            Give your agents the same context as your people. Keep their work
            visible, their reasoning traceable, and the important decisions in
            human hands.
          </p>
          <a
            className="m-inline-link"
            href={
              workspaceHref.startsWith("#")
                ? workspaceHref
                : `${workspaceHref}/board`
            }
          >
            Explore the agent board <ArrowUpRight size={15} />
          </a>
          <div className="m-agent-principle">
            <ShieldCheck size={19} />
            <span>
              <strong>You stay in control.</strong>Follow-ups are saved as
              drafts for review.
            </span>
          </div>
        </div>
        <div className="m-agent-flow">
          <div className="m-flow-heading">
            <span>
              <span /> A context-aware handoff
            </span>
            <small>Illustrative walkthrough</small>
          </div>
          <div className="m-flow-steps">
            {agentSteps.map(({ title, detail, icon: Icon }, i) => (
              <button
                key={title}
                onClick={() => setStep(i)}
                aria-pressed={step === i}
                className={i <= step ? "is-reached" : ""}
              >
                <span className="m-flow-icon">
                  {i < step ? <Check size={18} /> : <Icon size={18} />}
                </span>
                <span>
                  <strong>{title}</strong>
                  <span>{detail}</span>
                </span>
                {i === step && (
                  <span className="m-flow-current">
                    {i === 3 ? "Your review" : "In focus"}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="m-flow-result" key={step} aria-live="polite">
            <span>
              {step === 3 ? <ShieldCheck size={15} /> : <Sparkles size={15} />}
            </span>
            <p>
              {step === 0
                ? "The release date is now September 28."
                : step === 1
                  ? "Release handoff → earlier date → Rahul."
                  : step === 2
                    ? "Draft: review the release handoff against the new date."
                    : "Ready for Rahul to review. No message has been sent."}
            </p>
          </div>
          <button
            className="m-flow-next"
            onClick={() => setStep((step + 1) % 4)}
          >
            {step === 3 ? (
              <>
                <RotateCcw size={14} /> Replay walkthrough
              </>
            ) : (
              <>
                See the next step <ArrowRight size={14} />
              </>
            )}
          </button>
        </div>
      </div>
    </section>
  );
}

export function MemoryInterlude() {
  return (
    <section className="m-interlude">
      <div className="m-container">
        <div className="m-interlude-copy">
          <span className="m-eyebrow">Small pieces. A bigger picture.</span>
          <h2>
            A company is more
            <br />
            than the sum
            <br />
            of its meetings.
          </h2>
          <p>Give everything you know a place to connect.</p>
          <a href="#workspaces" className="m-button m-button-white">
            Find your shared memory <ArrowUpRight size={16} />
          </a>
        </div>
        <MemorySculpture />
      </div>
      <div className="m-interlude-baseline">
        <span>Gather the pieces.</span>
        <span>Connect the context.</span>
        <span>Remember what matters.</span>
      </div>
    </section>
  );
}

const faqs = [
  {
    q: "What is Minutes?",
    a: "Minutes is a company memory workspace. It connects meeting transcripts and email threads to decisions, commitments, people, and tracked work, so your team can understand what happened and what changed.",
  },
  {
    q: "What can I bring into a workspace?",
    a: "You can ingest meeting transcripts and email threads through the Sources page. Decisions, people, and commitments extracted from those sources become connected context. The homepage examples are illustrations; each workspace shows its own records.",
  },
  {
    q: "What happens when a decision changes?",
    a: "The new decision can supersede the old one without deleting its history. You can inspect the supporting source, revisit earlier facts, and review tracked work whose explicit dependencies point to a superseded decision.",
  },
  {
    q: "Do agents send messages on my behalf?",
    a: "Follow-up actions prepare local drafts for review. They do not send email or messages externally. The agent board makes task state and activity visible.",
  },
  {
    q: "Can I explore the project now?",
    a: "Yes. Open an available workspace below or create a new one. Existing workspaces expose their own sources, decisions, chat, timeline, and agent activity. Demo model responses are labeled in the workspace.",
  },
];
export function QuestionsSection() {
  return (
    <section className="m-faq-section m-container" id="questions">
      <div>
        <span className="m-eyebrow">A little more context</span>
        <h2>Good questions.</h2>
        <p>Here’s what to know before you jump in.</p>
      </div>
      <div className="m-faq-list">
        {faqs.map(({ q, a }) => (
          <details key={q}>
            <summary>
              {q}
              <Plus size={18} />
            </summary>
            <p>{a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className="m-footer">
      <div className="m-container">
        <div className="m-footer-top">
          <div>
            <MemoryMark />
            <p>
              The next chapter starts
              <br />
              with the whole story.
            </p>
            <a href="#workspaces">
              Open Minutes <ArrowUpRight size={17} />
            </a>
          </div>
          <nav aria-label="Footer">
            <div>
              <strong>Explore</strong>
              <a href="#how-it-works">How it works</a>
              <a href="#answers">Ask Minutes</a>
              <a href="#workspaces">Workspaces</a>
            </div>
            <div>
              <strong>A little context</strong>
              <a href="#inside-minutes">Why Minutes</a>
              <a href="#questions">Questions</a>
              <a
                href="https://github.com/FalkorDB/FalkorDB"
                target="_blank"
                rel="noreferrer"
              >
                FalkorDB <ArrowUpRight size={11} />
              </a>
            </div>
          </nav>
        </div>
        <div className="m-footer-wordmark" aria-label="Minutes">
          minutes<span>.</span>
        </div>
        <div className="m-footer-bottom">
          <span>Made with context. Built by Team Vulcan.</span>
          <span>Company memory, powered by FalkorDB</span>
          <a href="#main-content">
            Back to top <ArrowUpRight size={12} />
          </a>
        </div>
      </div>
    </footer>
  );
}
