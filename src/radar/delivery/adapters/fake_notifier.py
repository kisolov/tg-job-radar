class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edits: list[tuple[int, str]] = []
        self.fail_next = 0

    async def send(self, text: str, parse_mode: str = "HTML") -> int:
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("telegram недоступен")
        self.sent.append(text)
        return len(self.sent)

    async def edit(self, message_id: int, text: str) -> None:
        self.edits.append((message_id, text))

    async def notify(self, text: str) -> None:  # AlertSink поверх того же бота
        await self.send(text)
