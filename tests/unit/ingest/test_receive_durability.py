"""I5: сообщение не теряется, если обработка упала после отметки «видели»."""
from radar.sources.entities import SourceKind


class FlakySink:
    def __init__(self, fails: int):
        self.fails, self.got = fails, []

    async def submit(self, msg):
        if self.fails:
            self.fails -= 1
            raise TimeoutError("пул соединений исчерпан")
        self.got.append(msg)


async def test_failed_processing_is_retried_by_next_poll(world):
    a = await world.add_account()
    ch = await world.add_source("chan_one", SourceKind.channel, 1, account=a)
    world.tg.post(ch.id, 5, "вакансия", date=world.clock.now())
    sink = FlakySink(fails=1)
    world.receive._sink = sink
    gw = world.tg.factory(a)
    await world.poll.execute(a.id, gw)
    assert sink.got == [] and (await world.sources.get(ch.id)).last_message_id == 0  # курсор не ушёл вперёд
    world.clock.advance(301)
    await world.poll.execute(a.id, gw)
    assert [m.message_id for m in sink.got] == [5]


async def test_live_failure_then_poll_picks_message_up(world):
    a = await world.add_account()
    ch = await world.add_source("grp_one", SourceKind.group, 2, account=a)
    await world.sources.set_joined(ch.id)
    msg = world.tg.post(ch.id, 9, "заказ", date=world.clock.now())
    sink = FlakySink(fails=1)
    world.receive._sink = sink
    try:
        await world.receive.execute(msg)
    except TimeoutError:
        pass
    await world.poll.execute(a.id, world.tg.factory(a))
    assert [m.message_id for m in sink.got] == [9]
