"""Learn from a call once it is resolved. Never delays or breaks the resolve itself."""

from __future__ import annotations

import logging
import threading

from bellhop.domain.events import CallResolved
from bellhop.ports import CallRepository, EventBus, ResidentRepository
from bellhop.services.memory_learner import MemoryLearner
from bellhop.services.memory_service import MemoryService

logger = logging.getLogger(__name__)

KNOWN_FACTS = 20  # already-stored facts shown to the extractor so it does not repeat them


class LearnOnResolve:
    """Runs the MemoryLearner on the transcript of each resolved call.

    The model call can take seconds, so by default it runs on a background thread: the robot's
    resolve request returns at once. Tests pass background=False to run it inline.
    """

    def __init__(
        self,
        calls: CallRepository,
        residents: ResidentRepository,
        memory: MemoryService,
        learner: MemoryLearner,
        bus: EventBus,
        background: bool = True,
    ) -> None:
        self._calls = calls
        self._residents = residents
        self._memory = memory
        self._learner = learner
        self._background = background
        bus.subscribe(CallResolved, self._on_resolved)

    def _on_resolved(self, event: CallResolved) -> None:
        if self._background:
            threading.Thread(target=self._learn, args=(event.call_id,), daemon=True).start()
        else:
            self._learn(event.call_id)

    def _learn(self, call_id: str) -> None:
        try:
            call = self._calls.get(call_id)
            if call is None or call.resident_id is None:
                return
            if not any(t.speaker == "resident" for t in call.transcript):
                return
            resident = self._residents.get(call.resident_id)
            known = self._memory.recall(call.resident_id, "", k=KNOWN_FACTS)
            self._learner.learn(
                call.resident_id,
                call.transcript,
                resident_name=resident.name if resident else None,
                known_facts=[f.text for f in known],
            )
        except Exception:
            logger.exception("learning from call %s failed", call_id)
