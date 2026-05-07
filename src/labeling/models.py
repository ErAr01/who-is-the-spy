from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.labeling.taxonomy import (
    AgeGroup,
    BodyBuild,
    CharacterType,
    ClothingPrimaryColor,
    EyeColor,
    FaceShape,
    FacialHair,
    FranchiseKind,
    GenderPresentation,
    Glasses,
    HairColor,
    HairLength,
    HairStyle,
    Headwear,
    Mood,
    Pose,
    SkinTone,
)


class CardTags(BaseModel):
    character_type: CharacterType
    franchise_kind: FranchiseKind = FranchiseKind.NONE
    gender_presentation: GenderPresentation
    age_group: AgeGroup
    body_build: BodyBuild = BodyBuild.UNKNOWN
    face_shape: FaceShape = FaceShape.UNKNOWN
    hair_color: HairColor
    hair_length: HairLength
    hair_style: HairStyle
    eye_color: EyeColor
    skin_tone: SkinTone
    facial_hair: FacialHair
    glasses: Glasses
    headwear: Headwear
    clothing_primary_color: ClothingPrimaryColor
    mood: Mood
    pose: Pose
    accessories: list[str] = Field(default_factory=list, max_length=6)
    distinct_marks: list[str] = Field(default_factory=list, max_length=4)
    notable_features: list[str] = Field(default_factory=list, max_length=10)

    model_config = ConfigDict(use_enum_values=True)


class CardRecord(BaseModel):
    id: str
    name: str
    wiki_url: str | None = None
    image_sha256: str
    tags: CardTags
    appearance_text: str
    embedding_model: str
    vision_model: str
    labeled_at: datetime
    dataset_categories: list[str] = Field(default_factory=list)
    notes: str | None = None


class PairResult(BaseModel):
    card_a: CardRecord
    card_b: CardRecord
    similarity: float
    k_used: int
    candidates_count: int
    breakdown: dict[str, str | int | float] = Field(default_factory=dict)

