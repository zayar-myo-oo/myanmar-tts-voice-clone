"""Errors carry a stable code + a Burmese message with the next step for the user."""
from __future__ import annotations


class RecapError(RuntimeError):
    def __init__(self, code: str, message_my: str, detail: str = ""):
        super().__init__(f"[{code}] {message_my}" + (f"\n{detail}" if detail else ""))
        self.code = code
        self.message_my = message_my
        self.detail = detail

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message_my, "detail": self.detail[-4000:]}


class Cancelled(RecapError):
    def __init__(self) -> None:
        super().__init__("cancelled", "အလုပ်ကို ရပ်လိုက်ပါပြီ။ ပြန်စချင်ရင် Retry နှိပ်ပါ။")


def out_of_vram(model: str) -> RecapError:
    return RecapError("out_of_vram", f"GPU memory (VRAM) မလောက်ပါ ({model})။ Settings မှာ model အသေးကို ရွေးပြီး ပြန်စမ်းပါ။")


def missing_model(name: str, hint: str) -> RecapError:
    return RecapError("missing_model", f"Model '{name}' မရှိသေးပါ။ {hint}")
