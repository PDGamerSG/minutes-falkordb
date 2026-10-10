import { ArrowUpRight } from "lucide-react";
import { AskMinutesButton } from "./LandingAssistant";

const questions = [
  { question: "What changed while I was away?", detail: "Find the decisions that moved." },
  { question: "Why did we make that decision?", detail: "Follow the answer to its source." },
  { question: "Who’s taking this forward?", detail: "See the people and the open work." },
];

export function ContextQuestions() {
  return <section className="mq-section" aria-labelledby="context-questions-title">
    <div className="mq-intro"><h2 id="context-questions-title">Walk in with<br /><span>the context.</span></h2><p>A few days away. A new project.<br />A conversation you missed.<br />Start with what you need to know.</p><span className="mq-invitation">A question is all it takes.<svg viewBox="0 0 74 18" fill="none" aria-hidden="true"><path d="M1 10c14 0 17-8 31-8s17 12 31 12h9m-6-5 6 5-6 3" /></svg></span></div>
    <div className="mq-questions">
      {questions.map(({ question, detail }) => <AskMinutesButton key={question} question={question} className="mq-question"><span><strong>{question}</strong><small>{detail}</small></span><ArrowUpRight size={22} aria-hidden="true" /></AskMinutesButton>)}
      <p className="mq-note">Opens the Minutes assistant. Your question comes with you.</p>
    </div>
  </section>;
}
