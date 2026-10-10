"""The domain contract: the one schema every GreenIQ module reads and writes.

Inputs (``Property`` + ``MonthlyReading``) are validated strictly: malformed or
impossible values are rejected. Merely *missing* or *conflicting* information is not an
error; it flows through as "unknown" and is handled explicitly by the engines.

Outputs (``Receipt`` and the result models) carry provenance on every number.
Schema changes are additive: new optional fields, never renames.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "1.0"

PropertyType = Literal["detached", "semi_detached", "terraced", "bungalow", "flat"]
FlatPosition = Literal["ground", "mid", "top"]
AgeBand = Literal["pre_1919", "1919_1944", "1945_1964", "1965_1980", "1981_2002", "post_2002"]
WallType = Literal["solid", "cavity"]
Glazing = Literal["single", "secondary", "double_pre_2002", "double_post_2002", "triple"]
HeatingSystem = Literal[
    "gas_boiler_noncondensing",
    "gas_boiler_condensing",
    "electric_storage",
    "electric_direct",
    "air_source_heat_pump",
    "ground_source_heat_pump",
]
Controls = Literal[
    "none", "programmer_thermostat", "programmer_thermostat_trvs", "smart_thermostat", "smart_zoned"
]
RoofOrientation = Literal["south", "east_west", "north"]
Shading = Literal["low", "medium", "high"]
EpcBand = Literal["A", "B", "C", "D", "E", "F", "G"]
Fuel = Literal["electricity", "gas"]
Region = Literal["london", "south_east", "south_west", "midlands", "north", "wales", "scotland"]

FUELS: tuple[Fuel, ...] = ("electricity", "gas")
AGE_BANDS: tuple[str, ...] = AgeBand.__args__  # oldest → newest

# How an input value came to be known. Shown next to every number in the UI.
Basis = Literal[
    "observed",  # stated in the property record or metered
    "derived",  # follows logically from other observed fields (e.g. mid-floor flat → no loft)
    "assumed",  # documented age-band default (RdSAP-style), used when the field is unknown
    "estimated",  # produced by a model (e.g. ML baseline energy, estimated rating)
    "not_applicable",  # the concept does not apply to this home
    "missing",  # unknown and no defensible default exists
]

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class MonthlyReading(BaseModel):
    """One month of metered purchases for one fuel. ``kwh=None`` means the read is missing."""

    model_config = ConfigDict(extra="forbid")

    month: str
    fuel: Fuel
    kwh: float | None = Field(default=None, ge=0, le=100_000)

    @field_validator("month")
    @classmethod
    def _month_format(cls, v: str) -> str:
        if not _MONTH_RE.match(v):
            raise ValueError("month must be formatted YYYY-MM")
        return v


class Property(BaseModel):
    """A home as recorded. Every characteristic is optional except identity, region and type."""

    model_config = ConfigDict(extra="forbid")

    property_id: str = Field(min_length=1, max_length=64)
    customer_id: str | None = Field(default=None, max_length=64)
    region: Region
    property_type: PropertyType
    flat_position: FlatPosition | None = None
    age_band: AgeBand | None = None
    floor_area_m2: float | None = Field(default=None, gt=15, lt=1500)

    wall_type: WallType | None = None
    wall_insulated: bool | None = None
    has_loft: bool | None = None
    loft_insulation_mm: int | None = Field(default=None, ge=0, le=600)
    floor_insulated: bool | None = None
    glazing: Glazing | None = None

    heating_system: HeatingSystem | None = None
    boiler_age_years: int | None = Field(default=None, ge=0, le=80)
    has_gas_connection: bool | None = None
    controls: Controls | None = None

    solar_pv_kwp: float | None = Field(default=None, ge=0, le=25)
    roof_orientation: RoofOrientation | None = None
    roof_shading: Shading | None = None

    epc_band: EpcBand | None = None
    sap_score: int | None = Field(default=None, ge=1, le=150)
    epc_year: int | None = Field(default=None, ge=2007, le=2030)

    listed_or_conservation: bool | None = None
    outdoor_space: bool | None = None

    meter_readings: list[MonthlyReading] = Field(default_factory=list)

    @model_validator(mode="after")
    def _structural_rules(self) -> "Property":
        if self.property_type != "flat" and self.flat_position is not None:
            raise ValueError("flat_position is only valid when property_type is 'flat'")
        seen: set[tuple[str, str]] = set()
        for r in self.meter_readings:
            key = (r.month, r.fuel)
            if key in seen:
                raise ValueError(f"duplicate meter reading for {r.fuel} in {r.month}")
            seen.add(key)
        return self


class Receipt(BaseModel):
    """Provenance for one computed number: what went in, how, which version, which source."""

    output: str
    value: Any = None
    unit: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    method: str
    method_version: str
    provider: str = "deterministic"
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Resolved(BaseModel):
    """An input value together with how we know it."""

    value: Any = None
    basis: Basis
    note: str | None = None

    @property
    def known(self) -> bool:
        return self.basis not in ("missing",)
