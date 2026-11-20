from datetime import date

from pydantic import BaseModel


class HolidayIn(BaseModel):
    holiday_date: date
    name: str
    kind: str | None = None
    note: str | None = None


class HolidayOut(BaseModel):
    id: str
    holiday_date: date
    name: str
    kind: str
    note: str | None = None


class HolidayCreated(BaseModel):
    id: str
