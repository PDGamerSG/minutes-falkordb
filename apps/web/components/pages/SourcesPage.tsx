"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Mail, Mic, Play, Upload } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import type { EmailThread, Episode, Job, Meeting } from "@/lib/types";
import { fmtClock, fmtDateTime, fmtDuration, fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { EmptyState, ErrorNote, Mono, PageHeader, Section } from "@/components/Page";
import { StateBadge } from "@/components/StateBadge";
import { EmailThreadView } from "@/components/EmailThreadView";

const SPEAKER_HUES = [300, 230, 165, 60, 25, 330, 130, 200];

function speakerStyle(idx: number): React.CSSProperties {
  const h = SPEAKER_HUES[idx % SPEAKER_HUES.length];
  return { "--spk": `oklch(0.62 0.14 ${h})` } as React.CSSProperties;
}

// ---------- import panel (shared by both tabs) ----------
function ImportPanel({
  tenant,
  kind,
  onDone,
}: {
  tenant: string;
  kind: "meeting" | "email";
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Poll the job every second until done/failed.
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.jobs.get(tenant, jobId);
        if (stop) return;
        setJob(j);
        if (j.status === "done") {
          toast.success(`${kind === "meeting" ? "Meeting" : "Thread"} ingested: ${j.stats.episodes} episodes, ${j.stats.facts} facts`);
          onDone();
          return;
        }
        if (j.status === "failed") {
          toast.error(j.error ?? "Ingestion failed");
          return;
        }
      } catch (e) {
        if (!stop) setErr(e instanceof Error ? e.message : String(e));
        return;
      }
      if (!stop) timer = window.setTimeout(tick, 1000);
    };
    let timer = window.setTimeout(tick, 400);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [jobId, tenant, kind, onDone]);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setJob(null);
    try {
      let res;
      if (kind === "meeting") {
        const text = await file.text();
        const json = JSON.parse(text) as unknown;
        res = await api.meetings.import(tenant, json);
      } else {
        res = await api.threads.import(tenant, file);
      }
      setJobId(res.job_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const accept = kind === "meeting" ? ".json,application/json" : ".json,.eml,.mbox,application/json,message/rfc822";
  const pct = Math.round((job?.progress ?? 0) * 100);

  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Upload className="size-4 text-muted-foreground" />
        <span className="text-sm font-medium">Import {kind === "meeting" ? "recorder export" : "email thread"}</span>
        <span className="text-xs text-muted-foreground">{kind === "meeting" ? ".json (recorder-format.md)" : ".json, .eml or .mbox"}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="max-w-full text-xs file:mr-2 file:rounded-md file:border file:bg-background file:px-2 file:py-1 file:text-xs file:font-medium"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button size="sm" onClick={submit} disabled={!file || busy}>
          {busy ? "Uploading…" : "Import"}
        </Button>
      </div>
      {err && <ErrorNote error={err} className="mt-2" />}
      {jobId && (
        <div className="mt-3 space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={job?.status ?? "queued"} pulse={job?.status === "running" || job?.status === "queued"} />
            <span className="font-mono text-muted-foreground">{jobId}</span>
            <span className="ml-auto font-medium">
              {job?.stage ?? "queued"} · <span className="tabular">{pct}%</span>
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
          {job && (
            <dl className="grid grid-cols-3 gap-x-3 gap-y-1 sm:grid-cols-6">
              {(Object.keys(job.stats) as Array<keyof Job["stats"]>).map((k) => (
                <div key={k}>
                  <dt className="text-[10px] tracking-wide text-muted-foreground uppercase">{k}</dt>
                  <dd className="font-semibold tabular">{fmtNum(job.stats[k])}</dd>
                </div>
              ))}
            </dl>
          )}
          {job?.error && <ErrorNote error={job.error} />}
        </div>
      )}
    </div>
  );
}

// ---------- meetings tab ----------
function MeetingDetail({ tenant, meeting, seekTo }: { tenant: string; meeting: Meeting; seekTo: number | null }) {
  const { data: episodes, error, loading } = useResource(() => api.meetings.episodes(tenant, meeting.id), [tenant, meeting.id]);
  const { data: hasAudio } = useResource(() => api.meetings.hasAudio(tenant, meeting.id), [tenant, meeting.id]);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  const speakers = useMemo(() => {
    const ids: string[] = [];
    for (const e of episodes ?? []) if (!ids.includes(e.speaker.id)) ids.push(e.speaker.id);
    return ids;
  }, [episodes]);

  const playAt = useCallback(
    (ms: number) => {
      const a = audioRef.current;
      if (!a) return;
      a.currentTime = ms / 1000;
      void a.play().catch(() => {});
    },
    [],
  );

  // Deep link: the episode at `t` is highlighted until playback moves on.
  const seekEpisodeId = useMemo(() => {
    if (seekTo == null || !episodes) return null;
    const ep = episodes.find((e) => seekTo >= e.t_start && seekTo < e.t_end) ?? episodes.find((e) => e.t_start >= seekTo) ?? null;
    return ep?.id ?? null;
  }, [seekTo, episodes]);
  const highlightedId = activeId ?? seekEpisodeId;

  useEffect(() => {
    if (seekTo == null || !seekEpisodeId) return;
    document.getElementById(`ep-${seekEpisodeId}`)?.scrollIntoView({ block: "center" });
    if (hasAudio) playAt(seekTo);
  }, [seekTo, seekEpisodeId, hasAudio, playAt]);

  // Follow playback.
  const onTime = () => {
    const a = audioRef.current;
    if (!a || !episodes) return;
    const ms = a.currentTime * 1000;
    const ep = episodes.find((e) => ms >= e.t_start && ms < e.t_end);
    if (ep && ep.id !== activeId) setActiveId(ep.id);
  };

  return (
    <div className="space-y-3">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-base font-semibold">{meeting.title}</h2>
          <StateBadge state={meeting.status} size="xs" />
          <span className="text-xs text-muted-foreground tabular">
            {fmtDateTime(meeting.started_at)} · {fmtDuration(meeting.ended_at != null ? meeting.ended_at - meeting.started_at : null)}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[11px] text-muted-foreground">
          <span>{meeting.id}</span>
          {meeting.source_uri && <span>{meeting.source_uri}</span>}
        </div>
      </div>

      {hasAudio ? (
        <audio ref={audioRef} controls preload="metadata" className="w-full" src={api.meetings.audioUrl(tenant, meeting.id)} onTimeUpdate={onTime} />
      ) : (
        <div className="rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
          {hasAudio === undefined ? "Checking for audio…" : "No audio served for this meeting (source_uri not under data/meetings, or API offline)."}
        </div>
      )}

      {speakers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {speakers.map((id, i) => {
            const name = episodes?.find((e) => e.speaker.id === id)?.speaker.name ?? id;
            return (
              <span key={id} style={speakerStyle(i)} className="inline-flex h-5 items-center gap-1.5 rounded-md border border-(--spk)/30 bg-(--spk)/10 px-1.5 text-xs text-(--spk)">
                <Mic className="size-3" />
                {name}
              </span>
            );
          })}
        </div>
      )}

      {error && !episodes && <ErrorNote error={error} />}
      {loading && !episodes && (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      )}
      {episodes && (
        <ol className="space-y-1.5">
          {episodes.map((e: Episode) => {
            const idx = speakers.indexOf(e.speaker.id);
            const active = e.id === highlightedId;
            return (
              <li
                key={e.id}
                id={`ep-${e.id}`}
                style={speakerStyle(idx)}
                className={cn("grid grid-cols-[auto_1fr] gap-x-3 rounded-md border p-2 text-sm transition-colors", active && "border-primary/50 bg-primary/5")}
              >
                <div className="flex flex-col items-start gap-1">
                  <span className="inline-flex h-5 items-center rounded-md bg-(--spk)/12 px-1.5 text-xs font-medium text-(--spk)">{e.speaker.name}</span>
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button size="xs" variant="ghost" className="-ml-1 font-mono text-[11px] text-muted-foreground tabular" onClick={() => playAt(e.t_start)} disabled={!hasAudio} />
                      }
                    >
                      <Play className="size-3" /> {fmtClock(e.t_start)}
                    </TooltipTrigger>
                    <TooltipContent>{hasAudio ? `Play at ${fmtClock(e.t_start)}` : "No audio for this meeting"}</TooltipContent>
                  </Tooltip>
                </div>
                <div className="min-w-0">
                  <p className="leading-relaxed">{e.text}</p>
                  <div className="mt-1 flex flex-wrap gap-x-3 font-mono text-[10px] text-muted-foreground">
                    <span>{e.id}</span>
                    <span>seq {e.seq}</span>
                    <span>
                      {fmtClock(e.t_start)}–{fmtClock(e.t_end)}
                    </span>
                    <span>{fmtDateTime(e.t_occurred)}</span>
                  </div>
                </div>
              </li>
            );
          })}
          {episodes.length === 0 && <EmptyState title="No episodes" hint="The import may still be running." />}
        </ol>
      )}
    </div>
  );
}

function MeetingsTab({ tenant, selectedId, title, seekTo, onSelect }: { tenant: string; selectedId: string | null; title: string | null; seekTo: number | null; onSelect: (id: string) => void }) {
  const { data, error, loading, refetch } = useResource(() => api.meetings.list(tenant), [tenant]);

  // Resolve a title-only deep link (chat sources carry titles, not ids).
  useEffect(() => {
    if (selectedId || !title || !data) return;
    const hit = data.find((m) => m.title === title) ?? data.find((m) => m.title.toLowerCase().includes(title.toLowerCase()));
    if (hit) onSelect(hit.id);
  }, [selectedId, title, data, onSelect]);

  const selected = data?.find((m) => m.id === selectedId) ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="space-y-3">
        <ImportPanel tenant={tenant} kind="meeting" onDone={refetch} />
        {error && !data && <ErrorNote error={error} />}
        {loading && !data && <Skeleton className="h-64" />}
        {data && (
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Meeting</TableHead>
                  <TableHead className="text-right">Episodes</TableHead>
                  <TableHead className="text-right">Facts</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((m) => (
                  <TableRow key={m.id} data-state={m.id === selectedId ? "selected" : undefined} className="cursor-pointer" onClick={() => onSelect(m.id)}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Mic className="size-3.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <div className="truncate font-medium">{m.title}</div>
                          <div className="text-[11px] text-muted-foreground tabular">
                            {fmtDateTime(m.started_at)} · {fmtDuration(m.ended_at != null ? m.ended_at - m.started_at : null)}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular">{m.episodes}</TableCell>
                    <TableCell className="text-right tabular">{m.facts}</TableCell>
                    <TableCell>
                      <StateBadge state={m.status} size="xs" />
                    </TableCell>
                  </TableRow>
                ))}
                {data.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      No meetings yet. Import a recorder export above.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
      <div className="min-w-0">
        {selected ? (
          <MeetingDetail tenant={tenant} meeting={selected} seekTo={seekTo} />
        ) : (
          <EmptyState title="Select a meeting" hint="Episodes, speakers and timestamps appear here. Chat sources deep-link to a timestamp." className="h-full min-h-40" />
        )}
      </div>
    </div>
  );
}

// ---------- email tab ----------
function ThreadDetail({ tenant, thread, messageId }: { tenant: string; thread: EmailThread; messageId: string | null }) {
  const { data, error, loading } = useResource(() => api.threads.messages(tenant, thread.id), [tenant, thread.id]);
  return (
    <div className="space-y-3">
      <div>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-base font-semibold">{thread.subject}</h2>
          <StateBadge state={thread.status} size="xs" />
          <span className="text-xs text-muted-foreground tabular">
            {fmtDateTime(thread.started_at)} · {thread.messages} messages · {thread.facts} facts
          </span>
        </div>
        <Mono className="mt-0.5 block">{thread.id}</Mono>
      </div>
      {error && !data && <ErrorNote error={error} />}
      {loading && !data && <Skeleton className="h-40" />}
      {data && <EmailThreadView messages={data} highlightId={messageId} />}
    </div>
  );
}

function EmailTab({ tenant, selectedId, title, messageId, onSelect }: { tenant: string; selectedId: string | null; title: string | null; messageId: string | null; onSelect: (id: string) => void }) {
  const { data, error, loading, refetch } = useResource(() => api.threads.list(tenant), [tenant]);

  useEffect(() => {
    if (selectedId || !title || !data) return;
    const hit = data.find((t) => t.subject === title) ?? data.find((t) => t.subject.toLowerCase().includes(title.toLowerCase()));
    if (hit) onSelect(hit.id);
  }, [selectedId, title, data, onSelect]);

  const selected = data?.find((t) => t.id === selectedId) ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="space-y-3">
        <ImportPanel tenant={tenant} kind="email" onDone={refetch} />
        {error && !data && <ErrorNote error={error} />}
        {loading && !data && <Skeleton className="h-64" />}
        {data && (
          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Thread</TableHead>
                  <TableHead className="text-right">Messages</TableHead>
                  <TableHead className="text-right">Facts</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => (
                  <TableRow key={t.id} data-state={t.id === selectedId ? "selected" : undefined} className="cursor-pointer" onClick={() => onSelect(t.id)}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Mail className="size-3.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <div className="truncate font-medium">{t.subject}</div>
                          <div className="text-[11px] text-muted-foreground tabular">{fmtDateTime(t.started_at)}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular">{t.messages}</TableCell>
                    <TableCell className="text-right tabular">{t.facts}</TableCell>
                    <TableCell>
                      <StateBadge state={t.status} size="xs" />
                    </TableCell>
                  </TableRow>
                ))}
                {data.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      No threads yet. Import a .json, .eml or .mbox above.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
      <div className="min-w-0">
        {selected ? (
          <ThreadDetail tenant={tenant} thread={selected} messageId={messageId} />
        ) : (
          <EmptyState title="Select a thread" hint="Messages render as a thread with sender, recipients and time. Why panels deep-link to a message." className="h-full min-h-40" />
        )}
      </div>
    </div>
  );
}

// ---------- page ----------
export function SourcesPage({ team }: { team: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const tab = sp.get("tab") === "email" ? "email" : "meetings";
  const meeting = sp.get("meeting");
  const thread = sp.get("thread");
  const title = sp.get("title");
  const message = sp.get("message");
  const tRaw = sp.get("t");
  const seekTo = tRaw != null && tRaw !== "" && !Number.isNaN(Number(tRaw)) ? Number(tRaw) : null;

  const setParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(sp.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v == null || v === "") next.delete(k);
        else next.set(k, v);
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [router, pathname, sp],
  );

  const selectMeeting = useCallback((id: string) => setParams({ tab: "meetings", meeting: id, title: null, t: null }), [setParams]);
  const selectThread = useCallback((id: string) => setParams({ tab: "email", thread: id, title: null, message: null }), [setParams]);

  return (
    <div className="space-y-4">
      <PageHeader title="Sources" description="What the team actually said and wrote. Meetings arrive as diarized recorder exports; email threads as .json, .eml or .mbox. Both become Episodes in the tenant graph." />
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: String(v) })}>
        <TabsList variant="line">
          <TabsTrigger value="meetings">
            <Mic /> Meetings
          </TabsTrigger>
          <TabsTrigger value="email">
            <Mail /> Email threads
          </TabsTrigger>
        </TabsList>
        <TabsContent value="meetings">
          <Section className="mt-2">
            <MeetingsTab tenant={team} selectedId={meeting} title={tab === "meetings" ? title : null} seekTo={seekTo} onSelect={selectMeeting} />
          </Section>
        </TabsContent>
        <TabsContent value="email">
          <Section className="mt-2">
            <EmailTab tenant={team} selectedId={thread} title={tab === "email" ? title : null} messageId={message} onSelect={selectThread} />
          </Section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
