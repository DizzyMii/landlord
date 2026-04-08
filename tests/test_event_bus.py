import pytest
from landlord.event_bus import Event, EventBus


class TestEvent:
    def test_create_event(self):
        event = Event(
            tenant_id="abc123",
            event_type="checkpoint_reached",
            payload={"name": "schema_defined", "output": {"tables": []}},
        )
        assert event.tenant_id == "abc123"
        assert event.event_type == "checkpoint_reached"
        assert event.payload["name"] == "schema_defined"
        assert isinstance(event.timestamp, float)


class TestEventBus:
    @pytest.fixture
    def bus(self):
        return EventBus()

    async def test_subscribe_and_publish(self, bus):
        received = []

        async def handler(event: Event):
            received.append(event)

        await bus.subscribe("checkpoint_reached", handler)
        event = Event(tenant_id="t1", event_type="checkpoint_reached", payload={})
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].tenant_id == "t1"

    async def test_multiple_subscribers(self, bus):
        results = []

        async def handler_a(event: Event):
            results.append("a")

        async def handler_b(event: Event):
            results.append("b")

        await bus.subscribe("task_complete", handler_a)
        await bus.subscribe("task_complete", handler_b)
        await bus.publish(Event(tenant_id="t1", event_type="task_complete", payload={}))

        assert results == ["a", "b"]

    async def test_unsubscribe(self, bus):
        received = []

        async def handler(event: Event):
            received.append(event)

        await bus.subscribe("task_complete", handler)
        await bus.unsubscribe("task_complete", handler)
        await bus.publish(Event(tenant_id="t1", event_type="task_complete", payload={}))

        assert len(received) == 0

    async def test_publish_no_subscribers(self, bus):
        await bus.publish(Event(tenant_id="t1", event_type="unknown", payload={}))

    async def test_events_only_reach_matching_type(self, bus):
        received = []

        async def handler(event: Event):
            received.append(event)

        await bus.subscribe("checkpoint_reached", handler)
        await bus.publish(Event(tenant_id="t1", event_type="task_complete", payload={}))

        assert len(received) == 0
