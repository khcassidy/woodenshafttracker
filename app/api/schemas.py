"""Pydantic request models.

Decimal-carrying fields are StrictStr, never a bare JSON number: a JSON
number silently drops the entered text's trailing zeros before any
validator runs (23.230 -> the float 23.23), which would make the audit
requirement unsatisfiable. Every field defaults to None so the endpoint's
model_dump(exclude_unset=True) can distinguish "omitted" from "explicitly
cleared to null".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, StrictStr


class ShaftPatchRequest(BaseModel):
    spineA: StrictStr | None = None
    spineB: StrictStr | None = None
    weight: StrictStr | None = None
    weightUnit: Literal["g", "gr"] | None = None
    straightness: Literal["EXCELLENT", "OK", "BAD", "JUNK"] | None = None
    notes: StrictStr | None = None


class BulkPatchItem(BaseModel):
    seq: int
    fields: ShaftPatchRequest


class BulkPatchRequest(BaseModel):
    items: list[BulkPatchItem]


class BatchCreateRequest(BaseModel):
    batchNo: int
    expectedCount: int = Field(ge=0)
    nominalSpineLabel: StrictStr | None = None
    diameterId: int = 0
    woodId: int = 0
    shopId: int | None = None
    purchaseDate: StrictStr | None = None
    description: StrictStr | None = None
    entryMode: Literal["per_shaft", "per_field"] = "per_shaft"


class BatchExtendRequest(BaseModel):
    additionalCount: int = Field(gt=0)


class ShaftInsertRequest(BaseModel):
    afterSeq: int = Field(ge=0)


class BatchPatchRequest(BaseModel):
    entryMode: Literal["per_shaft", "per_field"] | None = None
    batchNo: int | None = None
    nominalSpineLabel: StrictStr | None = None
    diameterId: int | None = None
    woodId: int | None = None
    shopId: int | None = None
    purchaseDate: StrictStr | None = None
    description: StrictStr | None = None


class LookupCreateRequest(BaseModel):
    label: StrictStr
    sixtyFourths: int | None = None
    url: StrictStr | None = None
    notes: StrictStr | None = None


class LookupPatchRequest(BaseModel):
    label: StrictStr | None = None
    isActive: bool | None = None
    sixtyFourths: int | None = None
    url: StrictStr | None = None
    notes: StrictStr | None = None


class LookupOrderRequest(BaseModel):
    ids: list[int]


class ParamSetCreateRequest(BaseModel):
    name: StrictStr
    spineTolMlb: int
    weightTolCg: int
    objective: Literal["MAX_SET", "MAX_DOZENS"] = "MAX_DOZENS"
    dozenSize: int = Field(default=12, ge=2)
    specMinMlb: int
    specMaxMlb: int
    abTolCp: int
    minGroupSize: int = Field(default=3, ge=1)


class ParamSetPatchRequest(BaseModel):
    name: StrictStr | None = None
    spineTolMlb: int | None = None
    weightTolCg: int | None = None
    objective: Literal["MAX_SET", "MAX_DOZENS"] | None = None
    dozenSize: int | None = None
    specMinMlb: int | None = None
    specMaxMlb: int | None = None
    abTolCp: int | None = None
    minGroupSize: int | None = None


class SetCreateRequest(BaseModel):
    name: StrictStr
    diameterId: int
    woodId: int
    shaftIds: list[int] = Field(min_length=1)
    targetSize: int = Field(default=12, ge=1)
    notes: StrictStr | None = None
    idempotencyKey: StrictStr | None = None


class SetPatchRequest(BaseModel):
    notes: StrictStr | None = None


class SetMembersRequest(BaseModel):
    shaftIds: list[int] = Field(min_length=1)


class ImportCommitRequest(BaseModel):
    token: str


class EntryRulePatchRequest(BaseModel):
    spineMaxDp: int | None = None
    weightMaxDp: int | None = None
    spineStepCp: int | None = None
    weightStepCg: int | None = None
    spineHardMinCp: int | None = None
    spineHardMaxCp: int | None = None
    spineWarnMinCp: int | None = None
    spineWarnMaxCp: int | None = None
    weightHardMinCg: int | None = None
    weightHardMaxCg: int | None = None
    weightWarnMinCg: int | None = None
    weightWarnMaxCg: int | None = None
    batchOutlierSpineCp: int | None = None
    batchOutlierWeightCg: int | None = None
    grainsPerGram: StrictStr | None = None
