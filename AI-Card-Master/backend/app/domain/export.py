"""Direct Export domain: marketplace limits, card validation, and export views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class MarketplaceSellerError(Exception):
    """Raised by marketplace adapters when the seller API call fails."""


class MarketplacePlatform(StrEnum):
    """Supported one-click export destinations."""

    WILDBERRIES = "wildberries"
    OZON = "ozon"
    AMAZON = "amazon"


class ExportStatus(StrEnum):
    """Lifecycle of a marketplace draft export attempt."""

    VALIDATED = "validated"
    SUBMITTED = "submitted"
    FAILED = "failed"


class ValidationSeverity(StrEnum):
    """Severity of an automatic pre-export check."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class MarketplaceTextLimits:
    """Character limits for title and description on one marketplace."""

    title_min: int
    title_max: int
    description_min: int
    description_max: int
    characteristics_min: int
    characteristics_max: int
    characteristic_max_length: int


@dataclass(frozen=True, slots=True)
class MarketplacePhotoLimits:
    """Photo requirements enforced before calling the seller API."""

    min_count: int
    max_count: int
    min_width: int
    min_height: int
    max_bytes: int
    allowed_formats: frozenset[str]
    aspect_ratio: float | None
    aspect_ratio_tolerance: float
    require_portrait: bool


@dataclass(frozen=True, slots=True)
class MarketplaceRequirements:
    """Full automatic validation profile for one marketplace."""

    platform: MarketplacePlatform
    display_name: str
    text: MarketplaceTextLimits
    photo: MarketplacePhotoLimits
    notes: tuple[str, ...]


# Official / documented seller requirements (WB Content API, Ozon Seller, Amazon SP-API).
MARKETPLACE_REQUIREMENTS: dict[MarketplacePlatform, MarketplaceRequirements] = {
    MarketplacePlatform.WILDBERRIES: MarketplaceRequirements(
        platform=MarketplacePlatform.WILDBERRIES,
        display_name="Wildberries",
        text=MarketplaceTextLimits(
            title_min=10,
            title_max=100,
            description_min=1000,
            description_max=5000,
            characteristics_min=1,
            characteristics_max=12,
            characteristic_max_length=200,
        ),
        photo=MarketplacePhotoLimits(
            min_count=1,
            max_count=30,
            min_width=700,
            min_height=900,
            max_bytes=32 * 1024 * 1024,
            allowed_formats=frozenset({"JPEG", "JPG", "PNG", "WEBP", "BMP", "GIF"}),
            aspect_ratio=3 / 4,
            aspect_ratio_tolerance=0.05,
            require_portrait=True,
        ),
        notes=(
            "Cards are created asynchronously via POST /content/v2/cards/upload.",
            "Media is attached with POST /content/v3/media/save (public HTTPS links).",
            "Minimal image resolution is 700×900; recommended 900×1200 (3:4).",
        ),
    ),
    MarketplacePlatform.OZON: MarketplaceRequirements(
        platform=MarketplacePlatform.OZON,
        display_name="Ozon",
        text=MarketplaceTextLimits(
            title_min=10,
            title_max=200,
            description_min=1,
            description_max=6000,
            characteristics_min=1,
            characteristics_max=15,
            characteristic_max_length=250,
        ),
        photo=MarketplacePhotoLimits(
            min_count=1,
            max_count=15,
            min_width=900,
            min_height=1200,
            max_bytes=10 * 1024 * 1024,
            allowed_formats=frozenset({"JPEG", "JPG", "PNG", "WEBP"}),
            aspect_ratio=3 / 4,
            aspect_ratio_tolerance=0.05,
            require_portrait=True,
        ),
        notes=(
            "Draft cards are created via POST /v3/product/import.",
            "Images are passed as public HTTPS URLs in the import payload.",
            "Fashion categories require 900×1200 (3:4); max 15 images, 10 MB each.",
        ),
    ),
    MarketplacePlatform.AMAZON: MarketplaceRequirements(
        platform=MarketplacePlatform.AMAZON,
        display_name="Amazon",
        text=MarketplaceTextLimits(
            title_min=10,
            title_max=200,
            description_min=50,
            description_max=2000,
            characteristics_min=1,
            characteristics_max=5,
            characteristic_max_length=500,
        ),
        photo=MarketplacePhotoLimits(
            min_count=1,
            max_count=9,
            min_width=500,
            min_height=500,
            max_bytes=10 * 1024 * 1024,
            allowed_formats=frozenset({"JPEG", "JPG", "PNG", "GIF", "TIFF"}),
            aspect_ratio=None,
            aspect_ratio_tolerance=0.0,
            require_portrait=False,
        ),
        notes=(
            "Listings are submitted via putListingsItem (LISTING_PRODUCT_ONLY draft).",
            "item_name max is 200 characters; prefer ≥1000 px on the longest side.",
            "Main image should be on a pure white background (manual review advised).",
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class ImageAssetMeta:
    """Inspected bytes of one generated slide ready for marketplace upload."""

    object_key: str
    width: int
    height: int
    size_bytes: int
    format: str
    public_url: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One automatic limit or photo requirement violation."""

    code: str
    message: str
    severity: ValidationSeverity
    field: str | None = None


@dataclass(frozen=True, slots=True)
class CardValidationReport:
    """Result of automatic character and photo checks for one platform."""

    platform: MarketplacePlatform
    is_valid: bool
    issues: tuple[ValidationIssue, ...]
    title_length: int
    description_length: int
    photo_count: int
    requirements: MarketplaceRequirements

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is ValidationSeverity.WARNING)


@dataclass(frozen=True, slots=True)
class MarketplaceCredentialView:
    """Connected marketplace account without exposing secrets."""

    platform: MarketplacePlatform
    is_configured: bool
    label: str | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExportResultView:
    """Outcome of a one-click draft export."""

    id: UUID
    platform: MarketplacePlatform
    generation_job_id: UUID
    status: ExportStatus
    external_task_id: str | None
    external_offer_id: str | None
    vendor_code: str
    message: str
    validation: CardValidationReport
    created_at: datetime


def get_marketplace_requirements(platform: MarketplacePlatform) -> MarketplaceRequirements:
    """Return the validation profile for a marketplace."""

    return MARKETPLACE_REQUIREMENTS[platform]


def validate_card_for_marketplace(
    *,
    platform: MarketplacePlatform,
    title: str,
    description: str,
    characteristics: tuple[str, ...],
    images: tuple[ImageAssetMeta, ...],
) -> CardValidationReport:
    """Automatically check character limits and photo requirements."""

    requirements = get_marketplace_requirements(platform)
    issues: list[ValidationIssue] = []

    title_clean = " ".join(title.strip().split())
    description_clean = " ".join(description.strip().split())
    chars = tuple(" ".join(item.strip().split()) for item in characteristics if item.strip())

    _validate_text_field(
        issues,
        field="title",
        value=title_clean,
        min_len=requirements.text.title_min,
        max_len=requirements.text.title_max,
    )
    _validate_text_field(
        issues,
        field="description",
        value=description_clean,
        min_len=requirements.text.description_min,
        max_len=requirements.text.description_max,
    )

    if len(chars) < requirements.text.characteristics_min:
        issues.append(
            ValidationIssue(
                code="CHARACTERISTICS_TOO_FEW",
                field="characteristics",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"{requirements.display_name} requires at least "
                    f"{requirements.text.characteristics_min} characteristics."
                ),
            )
        )
    if len(chars) > requirements.text.characteristics_max:
        issues.append(
            ValidationIssue(
                code="CHARACTERISTICS_TOO_MANY",
                field="characteristics",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"{requirements.display_name} allows at most "
                    f"{requirements.text.characteristics_max} characteristics."
                ),
            )
        )
    for index, item in enumerate(chars):
        if len(item) > requirements.text.characteristic_max_length:
            issues.append(
                ValidationIssue(
                    code="CHARACTERISTIC_TOO_LONG",
                    field=f"characteristics[{index}]",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Characteristic #{index + 1} exceeds "
                        f"{requirements.text.characteristic_max_length} characters."
                    ),
                )
            )

    photo = requirements.photo
    if len(images) < photo.min_count:
        issues.append(
            ValidationIssue(
                code="PHOTOS_TOO_FEW",
                field="photos",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"{requirements.display_name} requires at least "
                    f"{photo.min_count} photo(s); got {len(images)}."
                ),
            )
        )
    if len(images) > photo.max_count:
        issues.append(
            ValidationIssue(
                code="PHOTOS_TOO_MANY",
                field="photos",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"{requirements.display_name} allows at most "
                    f"{photo.max_count} photos; got {len(images)}."
                ),
            )
        )

    for index, image in enumerate(images):
        _validate_image(issues, image=image, photo=photo, index=index, platform=requirements)

    # Soft guidance: WB search truncates titles around 60 chars.
    if (
        platform is MarketplacePlatform.WILDBERRIES
        and len(title_clean) > 60
        and len(title_clean) <= requirements.text.title_max
    ):
        issues.append(
            ValidationIssue(
                code="TITLE_SEARCH_TRUNCATION",
                field="title",
                severity=ValidationSeverity.WARNING,
                message=(
                    "Wildberries truncates search titles around 60 characters; "
                    "put the main keyword in the first 60."
                ),
            )
        )

    if platform is MarketplacePlatform.AMAZON and any(
        image.width < 1000 and image.height < 1000 for image in images
    ):
        issues.append(
            ValidationIssue(
                code="AMAZON_RESOLUTION_RECOMMENDATION",
                field="photos",
                severity=ValidationSeverity.WARNING,
                message=(
                    "Amazon recommends at least 1000 px on the longest side "
                    "for zoom; some images are below that."
                ),
            )
        )

    has_errors = any(i.severity is ValidationSeverity.ERROR for i in issues)
    return CardValidationReport(
        platform=platform,
        is_valid=not has_errors,
        issues=tuple(issues),
        title_length=len(title_clean),
        description_length=len(description_clean),
        photo_count=len(images),
        requirements=requirements,
    )


def _validate_text_field(
    issues: list[ValidationIssue],
    *,
    field: str,
    value: str,
    min_len: int,
    max_len: int,
) -> None:
    length = len(value)
    if length < min_len:
        issues.append(
            ValidationIssue(
                code=f"{field.upper()}_TOO_SHORT",
                field=field,
                severity=ValidationSeverity.ERROR,
                message=f"{field.capitalize()} must be at least {min_len} characters (got {length}).",
            )
        )
    if length > max_len:
        issues.append(
            ValidationIssue(
                code=f"{field.upper()}_TOO_LONG",
                field=field,
                severity=ValidationSeverity.ERROR,
                message=f"{field.capitalize()} must be at most {max_len} characters (got {length}).",
            )
        )


def _validate_image(
    issues: list[ValidationIssue],
    *,
    image: ImageAssetMeta,
    photo: MarketplacePhotoLimits,
    index: int,
    platform: MarketplaceRequirements,
) -> None:
    prefix = f"photos[{index}]"
    fmt = image.format.upper().replace("JPEG", "JPG")
    allowed = {item.upper().replace("JPEG", "JPG") for item in photo.allowed_formats}
    if fmt not in allowed and image.format.upper() not in photo.allowed_formats:
        issues.append(
            ValidationIssue(
                code="PHOTO_FORMAT_UNSUPPORTED",
                field=prefix,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Photo #{index + 1} format '{image.format}' is not accepted by "
                    f"{platform.display_name}. Allowed: {', '.join(sorted(photo.allowed_formats))}."
                ),
            )
        )
    if image.size_bytes > photo.max_bytes:
        issues.append(
            ValidationIssue(
                code="PHOTO_TOO_LARGE",
                field=prefix,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Photo #{index + 1} is {image.size_bytes} bytes; "
                    f"{platform.display_name} limit is {photo.max_bytes} bytes."
                ),
            )
        )
    if image.width < photo.min_width or image.height < photo.min_height:
        issues.append(
            ValidationIssue(
                code="PHOTO_RESOLUTION_TOO_LOW",
                field=prefix,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Photo #{index + 1} is {image.width}×{image.height}; "
                    f"{platform.display_name} requires at least "
                    f"{photo.min_width}×{photo.min_height}."
                ),
            )
        )
    if photo.require_portrait and image.height <= image.width:
        issues.append(
            ValidationIssue(
                code="PHOTO_NOT_PORTRAIT",
                field=prefix,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Photo #{index + 1} must be portrait (height > width) for "
                    f"{platform.display_name}."
                ),
            )
        )
    if photo.aspect_ratio is not None and image.height > 0:
        actual = image.width / image.height
        if abs(actual - photo.aspect_ratio) > photo.aspect_ratio_tolerance:
            issues.append(
                ValidationIssue(
                    code="PHOTO_ASPECT_RATIO",
                    field=prefix,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Photo #{index + 1} aspect ratio is {actual:.3f}; "
                        f"{platform.display_name} expects ~{photo.aspect_ratio:.3f} (3:4)."
                    ),
                )
            )
