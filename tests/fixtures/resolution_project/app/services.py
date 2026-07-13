from app.helpers import Helper


class Service:
    @staticmethod
    def run(payload: str) -> str:
        return Helper.work(payload)


class Schema:
    @staticmethod
    def from_dict(data: dict) -> "Schema":
        return Schema()
