export type Acceptance = {
  registration_id: string;
  sitting_id: string;
  registration_revision: number;
  accepted_at: string;
};
export type Invitation = {
  registration_id: string;
  sitting_id: string;
  publication_id: string;
  title: string;
  allowed_minutes: number;
  opens_at: string;
  closes_at: string;
  display_timezone: string;
  server_time: string;
  window_state: "upcoming" | "open" | "closed" | "withdrawn" | "cancelled";
  can_start: boolean;
  deadline_if_started_now: string | null;
  registration_revision: number;
  registration_status: string;
  acceptance: Acceptance | null;
  can_accept: boolean;
};
export type InvitationPage = {
  items: Invitation[];
  offset: number;
  limit: number;
  has_more: boolean;
  server_time: string;
};
export function invitationTime(instant: string, zone: string) {
  const match = /^UTC([+-])(\d{2}):(\d{2})$/.exec(zone);
  if (zone !== "UTC" && !match) return "Time unavailable";
  const offset = match
    ? (Number(match[2]) * 60 + Number(match[3])) * (match[1] === "+" ? 1 : -1)
    : 0;
  const value = new Date(Date.parse(instant) + offset * 60000);
  if (!Number.isFinite(value.getTime())) return "Time unavailable";
  return `${value.toISOString().slice(0, 16).replace("T", " ")} ${zone}`;
}
export function timingMessage(row: Invitation) {
  if (row.window_state === "cancelled")
    return "This sitting has been cancelled.";
  if (row.window_state === "withdrawn")
    return "Your registration has been withdrawn.";
  if (row.window_state === "closed") return "The sitting window has closed.";
  if (row.window_state === "upcoming") return "The sitting has not opened yet.";
  return "The sitting window is open. Exam delivery is not available in this workspace yet.";
}
