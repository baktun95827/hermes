"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Play, RotateCcw } from "lucide-react";

type SubmitState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "error"; message: string };

export function ManualIngestForm() {
  const router = useRouter();
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState({ status: "submitting" });
    const form = new FormData(event.currentTarget);
    const payload = {
      title: String(form.get("title") ?? ""),
      url: String(form.get("url") ?? ""),
      user_label: String(form.get("user_label") ?? "user_note"),
      content_type: String(form.get("content_type") ?? "note"),
      text: String(form.get("text") ?? ""),
      requires_verification: form.get("requires_verification") === "on"
    };
    const response = await fetch("/api/ingest-text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = (await response.json()) as { job_id?: string; error?: string };
    if (!response.ok || !result.job_id) {
      setState({ status: "error", message: result.error ?? "Failed to create job" });
      return;
    }
    router.push(`/jobs/${result.job_id}`);
  }

  return (
    <form onSubmit={onSubmit}>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="title">标题</label>
          <input id="title" name="title" placeholder="英维克液冷讨论" />
        </div>
        <div className="field">
          <label htmlFor="url">URL</label>
          <input id="url" name="url" placeholder="https://..." />
        </div>
        <div className="field">
          <label htmlFor="user_label">来源标签</label>
          <input id="user_label" name="user_label" defaultValue="user_note" />
        </div>
        <div className="field">
          <label htmlFor="content_type">内容类型</label>
          <input id="content_type" name="content_type" defaultValue="note" />
        </div>
        <div className="field full">
          <label htmlFor="text">内容</label>
          <textarea
            id="text"
            name="text"
            required
            placeholder="粘贴新闻、研报片段、社交媒体内容或你的研究笔记"
          />
        </div>
      </div>
      <div className="actions">
        <label className="check-row">
          <input type="checkbox" name="requires_verification" />
          需要额外验证
        </label>
        <button className="button" disabled={state.status === "submitting"} type="submit">
          <Play aria-hidden="true" />
          {state.status === "submitting" ? "Submitting" : "Submit analysis"}
        </button>
        <button className="button secondary" type="reset">
          <RotateCcw aria-hidden="true" />
          Reset form
        </button>
      </div>
      {state.status === "error" ? <p className="notice">{state.message}</p> : null}
    </form>
  );
}
