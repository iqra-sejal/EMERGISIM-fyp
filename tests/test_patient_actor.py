import asyncio

import pytest

from emergisim.core.patient_actor import ActionEvent, PatientActor, SetMultiplier, StepResult

NEXT = {"early": "airway", "airway": "collapse", "collapse": "end"}
WINDOW = {"early": 0.10, "airway": 0.10, "collapse": 0.10, "stable": None, "end": None}


class ToyModel:
    def __init__(self):
        self.state = "early"
        self.log = []

    def handle_action(self, action_id, payload):
        self.log.append(("action", action_id, self.state))
        if action_id == "EPI" and self.state in NEXT:
            self.state = "stable"
            return StepResult(True)
        if action_id == "BAD":
            return StepResult(False, contraindication_id="C-01")
        return StepResult(False)

    def handle_timer_expiry(self):
        self.log.append(("timer", self.state))
        self.state = NEXT[self.state]
        return StepResult(True)

    def pacing_window_s(self, state):
        return WINDOW[state]

    def penalty_s(self, cid):
        return 0.08

    def snapshot(self):
        return {"state": self.state}


@pytest.mark.asyncio
async def test_timer_deteriorates_in_order():
    m = ToyModel()
    a = PatientActor("p1", m)
    await a.start()
    await asyncio.sleep(0.35)
    await a.stop()
    assert m.state == "end"
    assert [e[1] for e in m.log] == ["early", "airway", "collapse"]


@pytest.mark.asyncio
async def test_correct_action_cancels_pending_expiry():
    m = ToyModel()
    a = PatientActor("p1", m)
    await a.start()
    await asyncio.sleep(0.05)
    a.post(ActionEvent(action_id="EPI"))
    await asyncio.sleep(0.2)
    await a.stop()
    assert m.state == "stable"
    assert not any(e[0] == "timer" for e in m.log)


@pytest.mark.asyncio
async def test_stale_expiry_is_discarded():
    """Expiry already queued behind the action must not fire on the new state."""
    m = ToyModel()
    a = PatientActor("p1", m)
    await a.start()
    a.post(ActionEvent(action_id="EPI"))
    from emergisim.core.patient_actor import TimerExpired
    a.post(TimerExpired(epoch=1))  # epoch of the window the action just closed
    await asyncio.sleep(0.05)
    await a.stop()
    assert m.state == "stable"


@pytest.mark.asyncio
async def test_penalty_shortens_window():
    m = ToyModel()
    a = PatientActor("p1", m)
    await a.start()
    a.post(ActionEvent(action_id="BAD"))
    await asyncio.sleep(0.05)  # 0.10 - 0.08 penalty: expiry at ~0.02s
    await a.stop()
    assert m.state == "airway"


@pytest.mark.asyncio
async def test_multiplier_speeds_up_clock():
    m = ToyModel()
    a = PatientActor("p1", m)
    await a.start()
    a.post(SetMultiplier(value=4.0))  # remaining 0.10 -> 0.025, next window 0.025 too
    await asyncio.sleep(0.065)  # two sped-up windows (0.05s) pass, a third (0.075s) does not
    await a.stop()
    assert m.state == "collapse"


@pytest.mark.asyncio
async def test_four_patients_are_independent():
    models = [ToyModel() for _ in range(4)]
    actors = [PatientActor(f"p{i}", m) for i, m in enumerate(models)]
    for a in actors:
        await a.start()
    actors[2].post(ActionEvent(action_id="EPI"))
    await asyncio.sleep(0.15)
    for a in actors:
        await a.stop()
    assert [m.state for m in models] == ["airway", "airway", "stable", "airway"]


@pytest.mark.asyncio
async def test_late_dialogue_is_detectably_stale():
    m = ToyModel()
    a = PatientActor("p1", m)
    await a.start()
    epoch_at_request = a.epoch
    await asyncio.sleep(0.15)  # state moves on while "Claude" is thinking
    assert not a.is_current(epoch_at_request)
    await a.stop()
