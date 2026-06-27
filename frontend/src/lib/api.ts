// Client for the SkillLens backend, including the SSE-streaming resume parser.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// Mirrors the backend's TraceStep / SSE payload shapes (app/models/trace.py).
export interface TraceStep {
  step_id: string;
  step_type: string;
  agent_name: string;
  message: string;
  cost_usd: number | null;
  model_used: string | null;
  payload: Record<string, unknown> | null;
}

export interface StepEvent {
  run_id: string;
  step: TraceStep;
  running_cost_usd: number;
}

export interface CandidateProfile {
  full_name: string;
  email: string | null;
  summary: string;
  skills: { name: string; level: string; years_experience: number | null }[];
  experiences: {
    company: string;
    title: string;
    start_date: string;
    end_date: string | null;
    is_current: boolean;
  }[];
  target_role: string;
  total_years_experience: number;
  extraction_confidence: number;
}

export interface ParseCallbacks {
  onStep: (event: StepEvent) => void;
  onProfile: (profile: CandidateProfile, runningCostUsd: number) => void;
  onError: (message: string) => void;
}

// One parsed SSE frame: an optional event name plus its JSON data.
interface ParsedFrame {
  event: string | null;
  data: unknown;
}

function parseFrame(raw: string): ParsedFrame | null {
  let event: string | null = null;
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  return { event, data: JSON.parse(dataLines.join("\n")) };
}

/**
 * POST a resume to /profile/parse and consume the SSE stream. EventSource can't
 * POST multipart, so we read the streaming response body manually.
 */
export async function parseResume(
  file: File,
  targetRole: string,
  callbacks: ParseCallbacks,
  targetSeniority?: string,
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  form.append("target_role", targetRole);
  if (targetSeniority) form.append("target_seniority", targetSeniority);

  const resp = await fetch(`${API_BASE}/profile/parse`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok || !resp.body) {
    callbacks.onError(`request failed: ${resp.status}`);
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handle = (raw: string) => {
    const frame = parseFrame(raw);
    if (!frame) return;
    if (frame.event === "profile") {
      const d = frame.data as { profile: CandidateProfile; running_cost_usd: number };
      callbacks.onProfile(d.profile, d.running_cost_usd);
    } else if (frame.event === "error") {
      callbacks.onError((frame.data as { error: string }).error);
    } else {
      callbacks.onStep(frame.data as StepEvent);
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      handle(buffer.slice(0, sep));
      buffer = buffer.slice(sep + 2);
    }
  }
  if (buffer.trim()) handle(buffer);
}
