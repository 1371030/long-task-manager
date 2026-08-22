"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { createTask, listTasks, Task } from "../lib/api";

function formatCreateTaskError(err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(message);
    const detail = Array.isArray(parsed.detail) ? parsed.detail[0] : parsed.detail;
    if (typeof detail?.msg === "string") {
      return detail.msg.replace(/^Value error,\s*/, "");
    }
    if (typeof detail === "string") {
      return detail;
    }
  } catch {
    // Keep the original message when the server did not return JSON.
  }
  return message.replace(/^Error:\s*/, "");
}

export default function Home() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    listTasks().then(setTasks).catch((err) => setError(String(err)));
  }, []);

  async function handleCreateTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    const form = new FormData(event.currentTarget);
    const message = String(form.get("message") ?? "").trim();
    const constraints = String(form.get("constraints") ?? "").trim();

    const projectPath = String(form.get("project_path") ?? "").trim();
    const executorMode = String(form.get("executor_mode") || "agent") as "agent" | "codex";
    if (executorMode === "codex" && !projectPath) {
      setError("Project path is required when using tmux + Codex.");
      setIsSubmitting(false);
      return;
    }

    try {
      const task = await createTask({
        title: message.slice(0, 80) || "Untitled task",
        goal: message,
        constraints: constraints || undefined,
        initial_message: undefined,
        project_path: projectPath || undefined,
        executor_mode: executorMode,
      });
      router.push(`/tasks/${task.id}`);
    } catch (err) {
      setError(formatCreateTaskError(err));
      setIsSubmitting(false);
    }
  }

  return (
    <main className="stack">
      <section className="hero stack">
        <p className="eyebrow">MVP Phase 1B</p>
        <h1>Long Task Manager</h1>
        <p>Manage long-running tasks through steps, runs, approvals, timeline events, progress, and artifacts.</p>
      </section>

      {error && <pre className="error">{error}</pre>}

      <div className="grid">
        <section className="card stack">
          <h2>Create task</h2>
          <form className="stack" onSubmit={handleCreateTask}>
            <textarea name="message" placeholder="Describe the long-running task" required />
            <textarea name="constraints" placeholder="Constraints, if any" />
            <input name="project_path" placeholder="Project path, e.g. /Users/me/project" />
            <select name="executor_mode" defaultValue="agent">
              <option value="agent">Use text agent</option>
              <option value="codex">Use tmux + Codex</option>
            </select>
            <button disabled={isSubmitting}>{isSubmitting ? "Creating..." : "Create task"}</button>
          </form>
        </section>

        <section className="card stack">
          <h2>Recent tasks</h2>
          {tasks.length === 0 ? (
            <p>No tasks yet.</p>
          ) : (
            <div className="stack">
              {tasks.map((task) => (
                <Link className="item link-card" href={`/tasks/${task.id}`} key={task.id}>
                  <strong>{task.title}</strong>
                  <span className="badge">{task.status} · {task.executor_mode === "codex" ? "tmux + Codex" : "text agent"}</span>
                  <small>Updated {new Date(task.updated_at).toLocaleString()}</small>
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
