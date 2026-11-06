from radar.accounts.entities import DeviceProfile


class DefaultDeviceProfileProvider:
    """Пустой профиль: Telethon подставляет свои значения сам. Подделок под реальные устройства нет."""

    def get(self, name: str | None = None) -> DeviceProfile:
        if name not in (None, "default"):
            raise ValueError(f"Неизвестный профиль устройства: {name}")
        return DeviceProfile()
