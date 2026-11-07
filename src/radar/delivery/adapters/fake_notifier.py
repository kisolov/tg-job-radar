from radar.delivery.ports import DeliveryRejected


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.edits: list[tuple[int, str]] = []
        self.alerts: list[str] = []
        self.modes: list[str | None] = []  # parse_mode каждой попытки send
        self.fail_next = 0  # временный сбой (сеть)
        self.reject_next = 0  # Telegram отклонил сообщение (BadRequest)

    async def send(self, text: str, parse_mode: str | None = "HTML") -> int:
        self.modes.append(parse_mode)
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("telegram недоступен")
        if self.reject_next:
            self.reject_next -= 1
            raise DeliveryRejected("Bad Request: can't parse entities")
        self.sent.append(text)
        return len(self.sent)

    async def edit(self, message_id: int, text: str) -> None:
        self.edits.append((message_id, text))

    async def notify(self, text: str) -> None:  # AlertSink поверх того же бота
        self.alerts.append(text)
