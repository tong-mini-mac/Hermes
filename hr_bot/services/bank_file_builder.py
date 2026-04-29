"""Diagram BankFileBuilder.build — bank-specific transfer file stubs."""


class BankFileBuilder:
    _banks = ("SCB", "KBANK", "BBL")

    @classmethod
    def build(cls, bank_code: str, records: list) -> dict:
        bank = bank_code.upper()
        if bank not in cls._banks:
            bank = "OTHER"
        return {"bank": bank, "lines": len(records), "format": f"{bank}_EFT_v1"}
