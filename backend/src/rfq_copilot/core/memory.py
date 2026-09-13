"""In-memory session store (M0). Production uses LangGraph PostgresSaver (M2).

SessionState carries merged entities (slot filling) + rich messages (with
timestamps, tool_calls, citations) for session replay in admin panels.
"""

from dataclasses import dataclass, field


@dataclass
class SessionState:
    session_id: str
    user_ref: str | None = None
    messages: list[dict[str, object]] = field(default_factory=list)
    merged_entities: dict[str, str] = field(default_factory=dict)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str, user_ref: str | None = None) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id, user_ref=user_ref)
        return self._sessions[session_id]

    def append_message(self, session_id: str, role: str, content: str, **meta: object) -> None:
        msg: dict[str, object] = {"role": role, "content": content, **meta}
        self.get_or_create(session_id).messages.append(msg)

    def messages(self, session_id: str) -> list[dict[str, object]]:
        return list(self.get_or_create(session_id).messages)

    def merge_entities(self, session_id: str, new_entities: dict[str, str]) -> dict[str, str]:
        """Merge new entities into the session's accumulated slot state."""
        state = self.get_or_create(session_id)
        state.merged_entities.update(new_entities)
        return state.merged_entities

    def merged_entities(self, session_id: str) -> dict[str, str]:
        return dict(self.get_or_create(session_id).merged_entities)
