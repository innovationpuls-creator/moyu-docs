/**
 * RT3 — presence registry (arch 05 §14 awareness): tracks who is in a
 * resource room and broadcasts join/leave to the room through the
 * subscription dispatch path.
 */

export interface PresenceEvent {
	room: string;
	actorId: string;
	kind: "join" | "leave";
	occurredAt: string;
}

export class PresenceRegistry {
	private readonly members = new Map<string, Map<string, string>>(); // room -> actor -> since

	constructor(
		private readonly dispatch: (room: string, envelope: unknown) => number,
	) {}

	join(room: string, actorId: string): PresenceEvent {
		let roomMembers = this.members.get(room);
		if (!roomMembers) {
			roomMembers = new Map();
			this.members.set(room, roomMembers);
		}
		const occurredAt = new Date().toISOString();
		roomMembers.set(actorId, occurredAt);
		const event: PresenceEvent = { room, actorId, kind: "join", occurredAt };
		this.dispatch(room, { kind: "presence", payload: event });
		return event;
	}

	leave(room: string, actorId: string): PresenceEvent | null {
		const roomMembers = this.members.get(room);
		if (!roomMembers?.has(actorId)) return null;
		roomMembers.delete(actorId);
		if (roomMembers.size === 0) {
			this.members.delete(room);
		}
		const event: PresenceEvent = {
			room,
			actorId,
			kind: "leave",
			occurredAt: new Date().toISOString(),
		};
		this.dispatch(room, { kind: "presence", payload: event });
		return event;
	}

	membersOf(room: string): string[] {
		return [...(this.members.get(room)?.keys() ?? [])];
	}
}
