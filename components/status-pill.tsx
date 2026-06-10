type StatusPillProps = {
  status?: string;
};

export function StatusPill({ status = "created" }: StatusPillProps) {
  const normalized = ["created", "running", "done", "failed"].includes(status) ? status : "created";
  return <span className={`status-pill status-${normalized}`}>{normalized}</span>;
}
