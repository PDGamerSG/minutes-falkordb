export function MemoryMark({ className = "" }: { className?: string }) {
  return <span className={`m-memory-mark ${className}`} aria-hidden="true">{Array.from({ length: 9 }, (_, index) => <i key={index} />)}</span>;
}
