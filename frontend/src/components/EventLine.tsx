import { describeEvent, isKnownAction, whoOf, type EventLike } from "../lib/auditText";

/** One audit event as a sentence, keeping the raw action code and actor label visible (muted) so
 *  the line is still traceable to the record. */
export function EventLine({ event }: { event: EventLike }) {
  const known = isKnownAction(event.action);
  return (
    <>
      <strong>{whoOf(event)}</strong> {known ? describeEvent(event) : <>did <code>{event.action}</code></>}
      {event.reason && <span className="muted"> — {event.reason}</span>}
      {known && <span className="muted" style={{ fontSize: 12 }}> · <code>{event.action}</code></span>}
      {event.actor_display && event.actor_display !== event.actor && (
        <span className="muted" style={{ fontSize: 12 }}> · <code>{event.actor}</code></span>
      )}
    </>
  );
}
