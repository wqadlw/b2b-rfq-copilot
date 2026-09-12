"""In-memory session store (M0). Production uses LangGraph PostgresSaver (M2)."""

from dataclasses import dataclass, field


@dataclass
class SessionState:
    session_id: str
    user_ref: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get_or_create(self, session_id: str, user_ref: str | None = None) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id, user_ref=user_ref)
        return self._sessions[session_id]

    def append_message(self, session_id: str, role: str, content: str) -> None:
        self.get_or_create(session_id).messages.append({"role": role, "content": content})

    def messages(self, session_id: str) -> list[dict[str, str]]:
        return list(self.get_or_create(session_id).messages)
