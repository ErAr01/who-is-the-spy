from enum import StrEnum


class CharacterType(StrEnum):
    REAL_PERSON = "real_person"
    CARTOON_2D = "cartoon_2d"
    CARTOON_3D = "cartoon_3d"
    ANIME = "anime"
    COMIC_HERO = "comic_hero"
    MASCOT = "mascot"
    STYLIZED_OTHER = "stylized_other"


class FranchiseKind(StrEnum):
    NONE = "none"
    DISNEY = "disney"
    PIXAR = "pixar"
    DREAMWORKS = "dreamworks"
    MARVEL = "marvel"
    DC = "dc"
    ANIME_GENERAL = "anime_general"
    HOLLYWOOD = "hollywood"
    TV_SERIES = "tv_series"
    OTHER = "other"


class GenderPresentation(StrEnum):
    MALE = "male"
    FEMALE = "female"
    ANDROGYNOUS = "androgynous"
    NON_HUMAN = "non_human"
    UNKNOWN = "unknown"


class AgeGroup(StrEnum):
    CHILD = "child"
    TEEN = "teen"
    YOUNG_ADULT = "young_adult"
    ADULT = "adult"
    MIDDLE_AGED = "middle_aged"
    SENIOR = "senior"
    ELDER = "elder"
    AGELESS = "ageless"


class HairColor(StrEnum):
    BLACK = "black"
    BROWN = "brown"
    BLOND = "blond"
    RED = "red"
    AUBURN = "auburn"
    GRAY = "gray"
    SILVER = "silver"
    WHITE = "white"
    PINK = "pink"
    PURPLE = "purple"
    GREEN = "green"
    BLUE = "blue"
    BALD = "bald"
    UNNATURAL = "unnatural"
    OTHER = "other"
    HIDDEN = "hidden"


class HairLength(StrEnum):
    BALD = "bald"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    VERY_LONG = "very_long"
    HIDDEN = "hidden"


class HairStyle(StrEnum):
    STRAIGHT = "straight"
    WAVY = "wavy"
    CURLY = "curly"
    BUN = "bun"
    PONYTAIL = "ponytail"
    BRAIDS = "braids"
    SPIKY = "spiky"
    BALD = "bald"
    HIDDEN = "hidden"
    OTHER = "other"


class EyeColor(StrEnum):
    BROWN = "brown"
    BLUE = "blue"
    GREEN = "green"
    HAZEL = "hazel"
    AMBER = "amber"
    HETEROCHROMIA = "heterochromia"
    GRAY = "gray"
    BLACK = "black"
    UNNATURAL = "unnatural"
    HIDDEN = "hidden"


class SkinTone(StrEnum):
    VERY_LIGHT = "very_light"
    LIGHT = "light"
    MEDIUM = "medium"
    TAN = "tan"
    DARK = "dark"
    VERY_DARK = "very_dark"
    NON_HUMAN_COLOR = "non_human_color"


class BodyBuild(StrEnum):
    UNKNOWN = "unknown"
    SLIM = "slim"
    AVERAGE = "average"
    ATHLETIC = "athletic"
    MUSCULAR = "muscular"
    HEAVY = "heavy"


class FaceShape(StrEnum):
    UNKNOWN = "unknown"
    OVAL = "oval"
    ROUND = "round"
    SQUARE = "square"
    HEART = "heart"
    DIAMOND = "diamond"
    LONG = "long"


class FacialHair(StrEnum):
    NONE = "none"
    STUBBLE = "stubble"
    MUSTACHE = "mustache"
    BEARD = "beard"
    GOATEE = "goatee"
    FULL_BEARD = "full_beard"


class Glasses(StrEnum):
    NONE = "none"
    REGULAR = "regular"
    SUNGLASSES = "sunglasses"


class Headwear(StrEnum):
    NONE = "none"
    CAP = "cap"
    HAT = "hat"
    CROWN = "crown"
    HELMET = "helmet"
    HOOD = "hood"
    MASK = "mask"
    OTHER = "other"


class ClothingPrimaryColor(StrEnum):
    RED = "red"
    BLUE = "blue"
    GREEN = "green"
    YELLOW = "yellow"
    BLACK = "black"
    WHITE = "white"
    PURPLE = "purple"
    PINK = "pink"
    ORANGE = "orange"
    BROWN = "brown"
    GRAY = "gray"
    MIXED = "mixed"
    UNCLEAR = "unclear"


class Mood(StrEnum):
    HAPPY = "happy"
    SERIOUS = "serious"
    NEUTRAL = "neutral"
    ANGRY = "angry"
    SAD = "sad"
    MISCHIEVOUS = "mischievous"


class Pose(StrEnum):
    FRONT = "front"
    PROFILE = "profile"
    THREE_QUARTER = "three_quarter"
    LOOKING_AWAY = "looking_away"


APPEARANCE_CATEGORIES: tuple[str, ...] = (
    "gender_presentation",
    "age_group",
    "body_build",
    "face_shape",
    "hair_color",
    "hair_length",
    "hair_style",
    "eye_color",
    "skin_tone",
    "facial_hair",
    "glasses",
    "headwear",
    "clothing_primary_color",
    "mood",
    "pose",
    "accessories",
    "distinct_marks",
    "notable_features",
)

