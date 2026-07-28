from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Meta:
    hits: Optional[int] = None
    totalHits: Optional[int] = None
    nextCursor: Optional[str] = None


@dataclass
class MetaOrigin:
    origin: Optional[str] = None
    type: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class SampleItem:
    created_timestamp: Optional[str] = None
    timestamp: Optional[str] = None
    domain: Optional[int] = None

    meta_origin: MetaOrigin = field(default_factory=MetaOrigin)

    cs_id: Optional[str] = None
    product_name: Optional[str] = None
    serial_number: Optional[str] = None
    versio: Optional[str] = None

    auth_status_tag_id: Optional[str] = None
    auth_status_state: Optional[str] = None
    auth_scanned_tag_id: Optional[str] = None

    connected: Optional[bool] = None

    current_ac: Optional[float] = None
    current_ac1: Optional[float] = None
    current_ac2: Optional[float] = None
    current_ac3: Optional[float] = None

    voltage_ac: Optional[float] = None
    voltage_ac1: Optional[float] = None
    voltage_ac2: Optional[float] = None
    voltage_ac3: Optional[float] = None

    power_ac: Optional[float] = None
    power_factor: Optional[float] = None
    frequency: Optional[float] = None

    energy_ac: Optional[float] = None
    energy_ac_import: Optional[float] = None
    energy_ac_export: Optional[float] = None

    voltage_dc: Optional[float] = None
    current_dc: Optional[float] = None
    power_dc: Optional[float] = None

    number_phases: Optional[int] = None

    power_ac_min: Optional[float] = None
    power_ac_max: Optional[float] = None

    inverter_state: Optional[str] = None
    inverter_error: Optional[str] = None
    inverter_temperature: Optional[float] = None
    #optional noch dazu:
    #packpower[float] = None
    #packcapacity[float] = None
    #packvoltage[float] = None
    #packcurrent[float] = None




from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class ChargingSessionResponse:
    data: List[SampleItem] = field(default_factory=list)

    hits: Optional[int] = None
    totalHits: Optional[int] = None
    nextCursor: Optional[str] = None

    def add_sample(self, sample: SampleItem):
        self.data.append(sample)

    def to_dict(self):
        return asdict(self)