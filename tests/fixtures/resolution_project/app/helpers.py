class Helper:
    @staticmethod
    def work(payload: str) -> str:
        return deep_transform(payload)


def deep_transform(value: str) -> str:
    return value.upper()
