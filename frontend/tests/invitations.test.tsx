import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { InvitationSummary } from "../components/invitation-inbox";
import { Invitation, invitationTime, timingMessage } from "../lib/invitations";
const invitation: Invitation = {
  registration_id: "registration",
  sitting_id: "sitting",
  publication_id: "publication",
  title: "<script>Exam</script>",
  allowed_minutes: 50,
  opens_at: "2026-11-28T10:00:00Z",
  closes_at: "2026-11-28T12:00:00Z",
  display_timezone: "UTC+05:30",
  server_time: "2026-11-28T09:00:00Z",
  window_state: "upcoming",
  can_start: false,
  deadline_if_started_now: null,
  registration_revision: 2,
  registration_status: "active",
  acceptance: {
    registration_id: "registration",
    sitting_id: "sitting",
    registration_revision: 1,
    accepted_at: "2026-11-28T08:00:00Z",
  },
  can_accept: false,
};
describe("candidate invitation summary", () => {
  it("separates current allowance and historical receipt, escapes text and excludes private fields", () => {
    const html = renderToStaticMarkup(
      <InvitationSummary
        invitation={
          {
            ...invitation,
            content: "PRIVATE_CONTENT",
            accommodation_reason: "PRIVATE_REASON",
            policy: "PRIVATE_POLICY",
            candidate_user_id: "PRIVATE_ID",
          } as Invitation
        }
      />,
    );
    expect(html).toContain("50 minutes");
    expect(html).toContain("registration revision 1");
    expect(html).toContain("registration changed after");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("PRIVATE_");
    expect(html).not.toContain("<script>");
  });
  it.each(["cancelled", "withdrawn", "closed", "upcoming", "open"] as const)(
    "uses server state %s",
    (state) => {
      expect(timingMessage({ ...invitation, window_state: state })).toMatch(
        /cancelled|withdrawn|closed|not opened|window is open/,
      );
    },
  );
  it.each([
    ["2026-11-28T23:00:00Z", "UTC+05:30", "2026-11-29 04:30 UTC+05:30"],
    ["2026-11-28T01:00:00Z", "UTC-04:00", "2026-11-27 21:00 UTC-04:00"],
    ["2026-11-28T01:00:00Z", "UTC", "2026-11-28 01:00 UTC"],
    ["bad-date", "UTC", "Time unavailable"],
    ["2026-11-28T01:00:00Z", "Untrusted zone", "Time unavailable"],
  ])("formats fixed offset %s %s", (instant, zone, expected) =>
    expect(invitationTime(instant, zone)).toBe(expected),
  );
});
