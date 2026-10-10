import { Check, GitBranch, Mail, Mic, Users } from "lucide-react";

const nodes = [
  { className: "m-flow-node m-flow-node-meeting", icon: Mic, label: "Product kickoff", meta: "meeting" },
  { className: "m-flow-node m-flow-node-decision", icon: GitBranch, label: "UPI release", meta: "decision" },
  { className: "m-flow-node m-flow-node-followup", icon: Mail, label: "Payments follow-up", meta: "email" },
  { className: "m-flow-node m-flow-node-people", icon: Users, label: "Rahul + Priya", meta: "people" },
];

export function HeroFlow() {
  return (
    <div className="m-hero-flow" aria-hidden="true">
      <div className="m-flow-halo" />
      <svg className="m-flow-lines" viewBox="0 0 1200 570" fill="none" role="presentation">
        <path className="m-flow-path m-flow-path-a" d="M90 130C280 70 330 240 480 250S690 75 835 150s170 200 275 120" />
        <path className="m-flow-path m-flow-path-b" d="M40 420C220 330 330 455 475 385s190-170 340-115 210 125 340 15" />
        <path className="m-flow-path m-flow-path-c" d="M180 40C330 190 360 395 585 350s260-25 440 135" />
        <circle className="m-flow-dot m-flow-dot-a" cx="90" cy="130" r="4" />
        <circle className="m-flow-dot m-flow-dot-b" cx="835" cy="150" r="4" />
        <circle className="m-flow-dot m-flow-dot-c" cx="40" cy="420" r="4" />
        <circle className="m-flow-dot m-flow-dot-d" cx="815" cy="270" r="4" />
      </svg>
      {nodes.map(({ className, icon: Icon, label, meta }) => (
        <div className={className} key={label}>
          <span className="m-flow-node-icon"><Icon size={14} strokeWidth={1.8} /></span>
          <span><strong>{label}</strong><small>{meta}</small></span>
          <Check size={12} className="m-flow-check" />
        </div>
      ))}
      <div className="m-flow-core">
        <span className="m-flow-core-mark"><i /><i /><i /></span>
        <strong>shared memory</strong>
        <span><b /> always in context</span>
      </div>
    </div>
  );
}
