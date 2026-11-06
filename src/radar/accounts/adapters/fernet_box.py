from cryptography.fernet import Fernet, InvalidToken


class FernetSecretBox:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Не удалось расшифровать секрет: неверный USERBOT_STORE_KEY или повреждённые данные"
            ) from exc
