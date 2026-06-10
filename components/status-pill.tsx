type StatusPillProps = {
  status?: string;
};

export function StatusPill({ status = "created" }: StatusPillProps) {
  const normalized = ["created", "queued", "running", "done", "failed", "canceled"].includes(status) ? status : "created";
  return <span className={`status-pill status-${normalized}`}>{normalized}</span>;
}
