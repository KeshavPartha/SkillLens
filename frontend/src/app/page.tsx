"use client";

import { useState } from "react";
import {
  parseResume,
  type CandidateProfile,
  type StepEvent,
} from "@/lib/api";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [targetRole, setTargetRole] = useState("");
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [cost, setCost] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !targetRole.trim()) return;
    setSteps([]);
    setProfile(null);
    setError(null);
    setCost(0);
    setRunning(true);
    try {
      await parseResume(file, targetRole.trim(), {
        onStep: (ev) => {
          setSteps((prev) => [...prev, ev]);
          setCost(ev.running_cost_usd);
        },
        onProfile: (p, runningCost) => {
          setProfile(p);
          setCost(runningCost);
        },
        onError: (msg) => setError(msg),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-12">
      <h1 className="text-2xl font-semibold tracking-tight">SkillLens</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Upload a resume and a target role to extract a structured profile.
      </p>

      <form onSubmit={onSubmit} className="mt-8 space-y-4">
        <div>
          <label className="block text-sm font-medium">Resume (PDF)</label>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="mt-1 block w-full text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium">Target role</label>
          <input
            type="text"
            value={targetRole}
            onChange={(e) => setTargetRole(e.target.value)}
            placeholder="Senior Backend Engineer"
            className="mt-1 block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
        </div>
        <button
          type="submit"
          disabled={running || !file || !targetRole.trim()}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
        >
          {running ? "Parsing…" : "Parse resume"}
        </button>
      </form>

      {steps.length > 0 && (
        <section className="mt-8">
          <h2 className="text-sm font-semibold text-zinc-500">Agent activity</h2>
          <ul className="mt-2 space-y-1">
            {steps.map((s) => (
              <li
                key={s.step.step_id}
                className="flex items-center justify-between rounded-md bg-zinc-100 px-3 py-2 text-sm dark:bg-zinc-800"
              >
                <span>
                  <span className="font-mono text-xs text-zinc-500">
                    {s.step.step_type}
                  </span>{" "}
                  {s.step.message}
                </span>
                {s.step.cost_usd != null && (
                  <span className="font-mono text-xs text-zinc-500">
                    ${s.step.cost_usd.toFixed(4)}
                  </span>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-right font-mono text-xs text-zinc-500">
            Run cost: ${cost.toFixed(4)}
          </p>
        </section>
      )}

      {error && (
        <p className="mt-6 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      {profile && (
        <section className="mt-8 space-y-4">
          <div>
            <h2 className="text-xl font-semibold">{profile.full_name}</h2>
            <p className="text-sm text-zinc-500">
              Target: {profile.target_role} · {profile.total_years_experience} yrs
              experience · confidence{" "}
              {(profile.extraction_confidence * 100).toFixed(0)}%
            </p>
          </div>
          {profile.summary && <p className="text-sm">{profile.summary}</p>}

          <div>
            <h3 className="text-sm font-semibold text-zinc-500">Skills</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {profile.skills.map((sk) => (
                <span
                  key={sk.name}
                  className="rounded-full bg-zinc-100 px-3 py-1 text-xs dark:bg-zinc-800"
                >
                  {sk.name}
                  <span className="ml-1 text-zinc-400">{sk.level}</span>
                </span>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-zinc-500">Experience</h3>
            <ul className="mt-2 space-y-2">
              {profile.experiences.map((exp, i) => (
                <li key={i} className="text-sm">
                  <span className="font-medium">{exp.title}</span> · {exp.company}
                  <span className="ml-2 text-xs text-zinc-500">
                    {exp.start_date} – {exp.is_current ? "present" : exp.end_date}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}
    </main>
  );
}
