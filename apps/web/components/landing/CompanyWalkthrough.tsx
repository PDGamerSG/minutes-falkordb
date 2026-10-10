"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ArrowDown, Check } from "lucide-react";

const chapters = [
  { title: "Capture", description: "Bring the conversation in. Keep the people, the words, and the moment.", start: 0 },
  { title: "Connect", description: "Plans change. Link each update to the decision, without losing its history.", start: 8 },
  { title: "Recall", description: "Ask a question. Get the answer, the reason, and the sources behind it.", start: 16 },
];
const subscribe = () => () => {};

export function CompanyWalkthrough() {
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLElement>(null);
  const playIntent = useRef(false);
  const visible = useRef(false);
  const [time, setTime] = useState(0);
  const [failed, setFailed] = useState(false);
  const [showTranscript, setShowTranscript] = useState(false);
  const active = Math.min(2, Math.floor(time / 8));

  useEffect(() => {
    const video = videoRef.current;
    const container = containerRef.current;
    if (!video || !container) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    playIntent.current = !motion.matches;
    const syncPlayback = () => {
      if (playIntent.current && visible.current && !document.hidden) {
        // A tab switch can interrupt play(); keep autoplay intent for the next visibility change.
        void video.play().catch(() => {});
      } else video.pause();
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible.current = entry.isIntersecting;
      syncPlayback();
    }, { threshold: 0.3 });
    const updateMotion = () => {
      playIntent.current = !motion.matches;
      syncPlayback();
    };
    observer.observe(container);
    document.addEventListener("visibilitychange", syncPlayback);
    motion.addEventListener("change", updateMotion);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", syncPlayback);
      motion.removeEventListener("change", updateMotion);
      video.pause();
    };
  }, [mounted]);

  const seek = (nextTime: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = nextTime;
    setTime(nextTime);
  };

  return (
    <section className="m-walkthrough" id="company-memory" ref={containerRef} aria-labelledby="walkthrough-title">
      <div className="m-walkthrough-heading">
        <div><span className="m-walkthrough-eyebrow">How Minutes works</span><h2 id="walkthrough-title">A conversation. A connection. A clearer answer.</h2></div>
        <span className="m-walkthrough-length">The story in 24 seconds <ArrowDown size={14} aria-hidden="true" /></span>
      </div>
      <div className="m-walkthrough-frame">
        <div className="m-walkthrough-sidebar">
          <div className="m-chapters" role="group" aria-label="Video chapters">
            {chapters.map((chapter, index) => (
              <button type="button" key={chapter.title} aria-pressed={active === index} aria-controls="minutes-walkthrough-video" onClick={() => seek(chapter.start)} disabled={failed}>
                <span className="m-chapter-marker" aria-hidden="true">{index < active ? <Check size={13} /> : `0${index + 1}`}</span>
                <span className="m-chapter-copy"><strong>{chapter.title}</strong><span>{chapter.description}</span></span>
                <span className="m-chapter-progress" aria-hidden="true"><i style={{ transform: `scaleX(${active > index ? 1 : active === index ? (time - chapter.start) / 8 : 0})` }} /></span>
              </button>
            ))}
          </div>
          <p className="m-walkthrough-promise"><span aria-hidden="true">↳</span> Every answer has a history.</p>
        </div>
        <div className="m-walkthrough-media">
          <div className="m-walkthrough-screen">
            {mounted ? <video id="minutes-walkthrough-video" ref={videoRef} width="1200" height="900" muted loop playsInline preload="metadata" poster="/media/minutes-walkthrough-poster.jpg" aria-label="How Minutes captures conversations, connects decisions, and recalls answers" aria-describedby="walkthrough-description" onTimeUpdate={event => setTime(event.currentTarget.currentTime)} onError={() => { playIntent.current = false; setFailed(true); }}>
              <source src="/media/minutes-walkthrough.mp4" type="video/mp4" />
              <track kind="captions" src="/media/minutes-walkthrough.vtt" srcLang="en" label="English" />
              Your browser does not support video. Read the story below.
            </video> : <div className="m-walkthrough-poster" role="img" aria-label="A product kickoff and a follow-up email connected in Minutes" />}
            {failed && <div className="m-walkthrough-error"><strong>The video couldn’t load.</strong><span>You can still read the complete story below.</span><button type="button" onClick={() => setShowTranscript(true)}>Read the story</button></div>}
          </div>
        </div>
      </div>
      <div className="m-walkthrough-caption"><span id="walkthrough-description"><span className="m-caption-desktop">One decision, from the first conversation to the next step.</span><span className="m-caption-mobile">From conversation to context.</span> <span className="m-illustrative-label">Illustrative example.</span></span><div><button type="button" aria-expanded={showTranscript} aria-controls="walkthrough-transcript" onClick={() => setShowTranscript(!showTranscript)}>{showTranscript ? "Close story" : "Read the story"}</button></div></div>
      <div className="m-walkthrough-transcript" id="walkthrough-transcript" hidden={!showTranscript}>
        <p><strong>01 · Capture.</strong> In the product kickoff, Priya proposes September 24 for the UPI launch. A payments follow-up moves it to September 28 because sandbox access is delayed.</p>
        <p><strong>02 · Connect.</strong> Minutes links the update to the same release decision. The current date changes; the original commitment and both sources stay in the history.</p>
        <p><strong>03 · Recall.</strong> Ask “When are we launching UPI, and why?” Minutes answers September 28, explains the sandbox delay, and cites the sources. Rahul’s release handoff still uses the old date and needs review.</p>
      </div>
    </section>
  );
}
