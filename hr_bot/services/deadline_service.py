"""Diagram DeadlineService.remind — PND1 / SSO deadlines."""


class DeadlineService:
    @staticmethod
    def remind(doc: str, due: str, alert_days: int = 3) -> dict:
        return {"doc": doc, "due": due, "alert_days": alert_days}
