"""Plain data records shared by every module. The JSON files in data/ use the same field names."""

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class Member:
    name: str
    birth_date: str            # ISO date, e.g. "2019-04-02"
    pregnant: bool = False

    def age_on(self, day: date) -> int:
        """Age in completed years on the given day."""
        born = date.fromisoformat(self.birth_date)
        return day.year - born.year - ((day.month, day.day) < (born.month, born.day))

    @property
    def birth_year(self) -> int:
        return int(self.birth_date[:4])


@dataclass
class Household:
    id: str
    region: str
    site: str                  # distribution site the household collects from
    phone: str
    members: list[Member]      # members[0] is the head of household
    registered: str            # ISO date
    status: str = "active"     # active | inactive | merged
    sms_ok: bool = True        # agreed to receive SMS
    shelter_damaged: bool = False
    income_lost: bool = False
    disability: bool = False
    merged_into: str | None = None

    @property
    def head(self) -> Member:
        return self.members[0]

    @property
    def size(self) -> int:
        return len(self.members)

    @classmethod
    def from_dict(cls, d: dict) -> "Household":
        d = dict(d)
        d["members"] = [m if isinstance(m, Member) else Member(**m) for m in d["members"]]
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Lot:
    id: str
    warehouse_id: str
    sku: str
    qty: int
    received: str              # ISO date the batch arrived
    expires: str               # ISO date after which it may not be handed out


@dataclass
class Reservation:
    id: str
    warehouse_id: str
    sku: str
    qty: int
    lots: list[dict]           # [{"lot_id": ..., "qty": ...}], where the stock was taken from
    created: str               # ISO datetime
    expires_at: str            # ISO datetime when the hold lapses
    status: str = "held"       # held | released | fulfilled


@dataclass
class Delivery:
    household_id: str
    warehouse_id: str
    site: str
    sku: str
    kits: int
    route_id: str | None = None
    vehicle: str | None = None
    status: str = "planned"    # planned | unreachable

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Payment:
    id: str
    household_id: str
    amount: int                # whole dollars
    key: str                   # idempotency key, see payments/vouchers.py
    sent_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SmsMessage:
    id: str
    household_id: str
    phone: str
    template_id: str
    params: dict = field(default_factory=dict)
    text: str = ""
    queued_at: str = ""
    delivery: str = "pending"  # pending | delivered | failed (set by the SMS gateway)

    def to_dict(self) -> dict:
        return asdict(self)
