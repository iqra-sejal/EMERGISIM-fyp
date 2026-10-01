"""Concurrency model for parallel patients (TECHNICAL_SPEC section 9, P3 resolution).

Everything runs on FastAPI's single asyncio event loop. No threads, no
threading.Lock.

* One PatientActor per patient. Each owns an asyncio.Queue inbox and a single
  consumer task. Every state mutation (trainee action, timer expiry, Brain 1
  multiplier change) is an event in that queue, so events for one patient are
  applied strictly one at a time in FIFO order. Transitions are atomic by
  construction: no other code can observe or touch the state mid-handler.
* The pacing clock never mutates state. When a window expires it only posts a
  TimerExpired event. Each window carries an epoch; if the state changed (new
  epoch) before the event is processed, the stale expiry is discarded. This
  closes the "timer fires just after the correct action" race.
* Slow I/O (Claude dialogue, Whisper) never runs inside the handler. The
  handler returns an immutable snapshot; dialogue is generated in a separate
  task from that snapshot and dropped if the epoch moved on meanwhile, so a
  late LLM reply can never describe a state the patient has already left.
* CPU-heavy work (PPO inference) goes through asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


# --------------------------------------------------------------------------- events
@dataclass(frozen=True)
class Event:
    seq: int = field(default_factory=itertools.count().__next__, compare=False)


@dataclass(frozen=True)
class ActionEvent(Event):
    action_id: str = ""
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TimerExpired(Event):
    epoch: int = 0


@dataclass(frozen=True)
class SetMultiplier(Event):
    value: float = 1.0


@dataclass(frozen=True)
class ApplyPenalty(Event):
    seconds: float = 0.0


@dataclass(frozen=True)
class _Stop(Event):
    pass


# --------------------------------------------------------------------------- clock
class PacingClock:
    """One restartable countdown per patient. Posts TimerExpired(epoch) on expiry."""

    def __init__(self, post: Callable[[Event], None]):
        self._post = post
        self._handle: asyncio.TimerHandle | None = None
        self._deadline: float | None = None
        self.epoch = 0

    @property
    def remaining(self) -> float | None:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - asyncio.get_running_loop().time())

    def start(self, seconds: float) -> int:
        """Start a new window; any pending expiry from the old window becomes stale."""
        self.cancel()
        self.epoch += 1
        self._schedule(seconds)
        return self.epoch

    def subtract(self, seconds: float) -> None:
        """Contraindication penalty: shorten the current window, same epoch."""
        if self._deadline is None:
            return
        remaining = max(0.0, self.remaining - seconds)
        if self._handle:
            self._handle.cancel()
        self._schedule(remaining)

    def rescale(self, factor: float) -> None:
        """Brain 1 multiplier change mid-window: remaining time scales by factor."""
        if self._deadline is None:
            return
        remaining = self.remaining * factor
        if self._handle:
            self._handle.cancel()
        self._schedule(remaining)

    def cancel(self) -> None:
        if self._handle:
            self._handle.cancel()
        self._handle = None
        self._deadline = None

    def _schedule(self, seconds: float) -> None:
        loop = asyncio.get_running_loop()
        epoch = self.epoch
        self._deadline = loop.time() + seconds
        self._handle = loop.call_later(seconds, self._fire, epoch)

    def _fire(self, epoch: int) -> None:
        self._handle = None
        self._deadline = None
        self._post(TimerExpired(epoch=epoch))


# --------------------------------------------------------------------------- actor
class PatientModel(Protocol):
    """What a disease FSM must expose to run inside an actor."""

    state: str

    def handle_action(self, action_id: str, payload: dict) -> "StepResult": ...
    def handle_timer_expiry(self) -> "StepResult": ...
    def pacing_window_s(self, state: str) -> float | None: ...
    def penalty_s(self, action_id: str) -> float: ...
    def snapshot(self) -> dict: ...


@dataclass(frozen=True)
class StepResult:
    state_changed: bool
    contraindication_id: str | None = None
    log: dict = field(default_factory=dict)


class PatientActor:
    def __init__(
        self,
        patient_id: str,
        model: PatientModel,
        on_step: Callable[[str, StepResult, dict, int], Awaitable[None]] | None = None,
        multiplier: float = 1.0,
    ):
        self.patient_id = patient_id
        self.model = model
        self.multiplier = multiplier
        self._inbox: asyncio.Queue[Event] = asyncio.Queue()
        self._clock = PacingClock(self.post)
        self._on_step = on_step
        self._task: asyncio.Task | None = None
        self._side_tasks: set[asyncio.Task] = set()

    # ---- public API (safe to call from any coroutine on the loop)
    def post(self, event: Event) -> None:
        self._inbox.put_nowait(event)

    @property
    def epoch(self) -> int:
        return self._clock.epoch

    async def start(self) -> None:
        self._restart_window()
        self._task = asyncio.create_task(self._run(), name=f"patient-{self.patient_id}")

    async def stop(self) -> None:
        self.post(_Stop())
        if self._task:
            await self._task
        self._clock.cancel()
        for t in list(self._side_tasks):
            t.cancel()

    def spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        """Run slow I/O (e.g. dialogue generation) outside the event handler."""
        task = asyncio.ensure_future(coro)
        self._side_tasks.add(task)
        task.add_done_callback(self._side_tasks.discard)
        return task

    def is_current(self, epoch: int) -> bool:
        """True if a reply generated at `epoch` still describes the live state."""
        return epoch == self._clock.epoch

    # ---- internals
    def _restart_window(self) -> None:
        base = self.model.pacing_window_s(self.model.state)
        if base is None:
            self._clock.cancel()
            self._clock.epoch += 1  # terminal state: invalidate any pending expiry
        else:
            self._clock.start(base / self.multiplier)

    async def _run(self) -> None:
        while True:
            event = await self._inbox.get()
            if isinstance(event, _Stop):
                return
            result = self._apply(event)
            if result is not None and self._on_step is not None:
                await self._on_step(self.patient_id, result, self.model.snapshot(), self._clock.epoch)

    def _apply(self, event: Event) -> StepResult | None:
        match event:
            case TimerExpired(epoch=epoch):
                if epoch != self._clock.epoch:
                    return None  # stale: the state already moved on
                result = self.model.handle_timer_expiry()
                self._restart_window()
                return result
            case ActionEvent(action_id=action_id, payload=payload):
                result = self.model.handle_action(action_id, payload)
                if result.state_changed:
                    self._restart_window()
                elif result.contraindication_id:
                    self._clock.subtract(self.model.penalty_s(result.contraindication_id))
                return result
            case SetMultiplier(value=value):
                if value != self.multiplier:
                    self._clock.rescale(self.multiplier / value)
                    self.multiplier = value
                return None
            case ApplyPenalty(seconds=seconds):
                self._clock.subtract(seconds)
                return None
        return None
