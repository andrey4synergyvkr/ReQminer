from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class LinkMeta:
    """Метаданные связи: вид, роль и кратности."""
    kind: str
    role: str
    source_mult: str
    target_mult: str


class DependencyType(str, Enum):
    """Тип зависимости между требованиями."""

    UNSPECIFIED = "unspecified"


class TraceabilityType(str, Enum):
    """Тип трассируемой связи."""

    UNSPECIFIED = "unspecified"


class QualityAttrType(str, Enum):
    """Справочник категорий атрибутов модели качества."""

    UNSPECIFIED = "unspecified"


class LifecycleStatus(str, Enum):
    """Статус жизненного цикла требования."""

    EXTRACTED = "extracted"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    DRAFT = "draft"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    NEEDS_CLARIFICATION = "needs_clarification"
    DEPRECATED = "deprecated"


class ReviewDecision(str, Enum):
    """Решение эксперта по ручной проверке требования."""

    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_CLARIFICATION = "needs_clarification"
    REWORK = "rework"


class ConstraintCategory(str, Enum):
    """Категория ограничения."""

    REGULATORY = "regulatory"
    BUSINESS_RULE = "business_rule"
    TECHNOLOGY = "technology"
    ARCHITECTURE = "architecture"
    SCHEDULE = "schedule"
    BUDGET = "budget"
    INTERFACE = "interface"
    PHYSICAL = "physical"


class StrictnessLevel(str, Enum):
    """Степень жёсткости ограничения."""

    HARD_MANDATORY = "hard_mandatory"
    SOFT_PREFERRED = "soft_preferred"
    GUIDELINE = "guideline"


class ParsingStatus(str, Enum):
    """Статус парсинга Markdown-документа."""

    PENDING = "pending"
    PARSED = "parsed"
    FAILED = "failed"


class GlossaryTermStatus(str, Enum):
    """Статус термина глоссария."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class TermUsageStatus(str, Enum):
    """Статус использования термина."""

    DETECTED = "detected"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NEEDS_CLARIFICATION = "needs_clarification"


class TermRelationType(str, Enum):
    """Тип отношения между терминами глоссария."""

    SYNONYM = "synonym"
    BROADER = "broader"
    NARROWER = "narrower"
    RELATED = "related"
    ANTONYM = "antonym"


class Requirement(BaseModel, ABC):
    """Абстрактная сущность для любого требования/записи бэклога."""

    id: str
    title: str

    description: Optional[str] = None
    rationale: Optional[str] = None
    priority: Optional[str] = None
    lifecycle_status: LifecycleStatus = Field(default=LifecycleStatus.DRAFT)
    source: Optional[str] = None
    estimate: Optional[str] = None
    is_mandatory: bool = False
    confidence: Optional[float] = None
    origin: Optional[str] = None
    validated_at: Optional[datetime] = None

    raw_snippet: Optional[str] = None
    normalized_text: Optional[str] = None
    requirement_type: Optional[str] = None
    source_location: Optional[str] = None
    extracted_at: Optional[datetime] = None
    extraction_model: Optional[str] = None
    extraction_prompt: Optional[str] = None

    reviewed_by: Optional[str] = None
    review_decision: Optional[ReviewDecision] = None
    review_comment: Optional[str] = None
    validation_notes: Optional[str] = None

    must_satisfy: Annotated[
        Optional["DefinitionOfDone"],
        LinkMeta(kind="directed", role="mustSatisfy", source_mult="0..*", target_mult="0..*"),
    ] = Field(default=None)
    acceptance_criteria: Annotated[
        list["AcceptanceCriterion"],
        LinkMeta(kind="composition", role="has", source_mult="1", target_mult="0..*"),
    ] = Field(default_factory=list)
    confidence_history: Annotated[
        list["ConfidenceAssessment"],
        LinkMeta(kind="composition", role="hasConfidence", source_mult="1", target_mult="0..*"),
    ] = Field(default_factory=list)


class FunctionalRequirement(Requirement, ABC):
    """Абстрактное функциональное требование."""

    business_value: Optional[str] = None
    scope: Optional[str] = None

    constrained_by: Annotated[
        list["QualityGoal"],
        LinkMeta(kind="directed", role="constrainedBy", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)


class NonFunctionalRequirement(Requirement, ABC):
    """Абстрактное требование к качеству, ограничению или техническому свойству."""

    verification_method: Optional[str] = None
    measurement_method: Optional[str] = None


class Link(BaseModel, ABC):
    """Абстрактная связь между требованиями."""

    description: Optional[str] = None
    rationale: Optional[str] = None
    status: Optional[str] = None

    source: Annotated[
        "Requirement",
        LinkMeta(kind="directed", role="source", source_mult="0..*", target_mult="1"),
    ] = Field(...)
    target: Annotated[
        "Requirement",
        LinkMeta(kind="directed", role="target", source_mult="0..*", target_mult="1"),
    ] = Field(...)


class Constraint(BaseModel, ABC):
    """Абстрактное ограничение, сужающее пространство решений."""

    id: str
    name: str
    description: Optional[str] = None
    category: ConstraintCategory = Field(default=ConstraintCategory.REGULATORY)
    strictness: StrictnessLevel = Field(default=StrictnessLevel.HARD_MANDATORY)
    rationale: Optional[str] = None
    penalty: Optional[str] = None
    confidence: Optional[float] = None

    constrains_requirements: Annotated[
        list["Requirement"],
        LinkMeta(kind="directed", role="constrains", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)
    constrains_quality: Annotated[
        list["QualityGoal"],
        LinkMeta(kind="directed", role="constrains", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)
    generates_risks: Annotated[
        list["Risk"],
        LinkMeta(kind="directed", role="generates", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)
    dictates_stories: Annotated[
        list["TechnicalStory"],
        LinkMeta(kind="directed", role="dictates", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)
    uses_terms: Annotated[
        list["GlossaryTerm"],
        LinkMeta(kind="directed", role="usesTerm", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)


class Epic(FunctionalRequirement):
    """Крупная функциональная цель или большая область работ."""

    objective: Optional[str] = None
    target_release: Optional[str] = None
    success_metric: Optional[str] = None

    features: Annotated[
        list["Feature"],
        LinkMeta(kind="aggregation", role="groups", source_mult="0..1", target_mult="0..*"),
    ] = Field(default_factory=list)


class Feature(FunctionalRequirement):
    """Функциональность, детализирующая Epic."""

    benefit: Optional[str] = None
    target_iteration: Optional[str] = None
    acceptance_summary: Optional[str] = None

    user_stories: Annotated[
        list["UserStory"],
        LinkMeta(kind="aggregation", role="decomposesInto", source_mult="0..1", target_mult="0..*"),
    ] = Field(default_factory=list)


class UserStory(FunctionalRequirement):
    """Пользовательская история с ценностью для пользователя."""

    as_a: Optional[str] = None
    i_want: Optional[str] = None
    so_that: Optional[str] = None


class QualityGoal(NonFunctionalRequirement):
    """Измеримая цель качества системы."""

    metric_name: Optional[str] = None
    target_value: Optional[str] = None
    acceptable_threshold: Optional[str] = None
    monitoring_method: Optional[str] = None

    addresses: Annotated[
        list["QualityAttribute"],
        LinkMeta(kind="directed", role="addresses", source_mult="0..*", target_mult="1..*"),
    ] = Field(default_factory=list)


class TechnicalStory(NonFunctionalRequirement):
    """Техническая история для достижения целей качества."""

    technical_objective: Optional[str] = None
    implementation_approach: Optional[str] = None

    addresses: Annotated[
        list["QualityAttribute"],
        LinkMeta(kind="directed", role="addresses", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)
    supports: Annotated[
        list["FunctionalRequirement"],
        LinkMeta(kind="directed", role="supports", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)


class Dependency(Link):
    """Зависимость планирования или реализации между требованиями."""

    type: DependencyType = Field(default=DependencyType.UNSPECIFIED)
    planning_impact: Optional[str] = None


class TraceabilityLink(Link):
    """Трассируемая связь происхождения, реализации или проверки."""

    type: TraceabilityType = Field(default=TraceabilityType.UNSPECIFIED)
    direction: Optional[str] = None
    evidence: Optional[str] = None


class Criterion(BaseModel, ABC):
    """Абстрактный критерий (приёма или готовности)."""

    id: str
    description: str
    verification_method: Optional[str] = None
    mandatory: bool = False


class AcceptanceCriterion(Criterion):
    """Критерий приёма требования."""

    given_when_then: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None


class DoneCriterion(Criterion):
    """Конкретный пункт Definition of Done."""

    applies_to: Optional[str] = None
    evidence: Optional[str] = None


class DefinitionOfDone(BaseModel):
    """Набор критериев готовности."""

    id: str
    name: str
    scope: Optional[str] = None
    version: Optional[str] = None
    active: bool = True

    contains: Annotated[
        list["DoneCriterion"],
        LinkMeta(kind="composition", role="contains", source_mult="1", target_mult="1..*"),
    ] = Field(default_factory=list, min_length=1)
    enforces: Annotated[
        list["QualityGoal"],
        LinkMeta(kind="directed", role="enforces", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)


class QualityAttribute(BaseModel):
    """Конкретный атрибут качества по выбранной модели качества."""

    id: str
    code: Optional[str] = None
    name: str
    description: Optional[str] = None
    model: Optional[str] = None
    category: QualityAttrType = Field(default=QualityAttrType.UNSPECIFIED)


class Risk(BaseModel):
    """Риск, влияющий на требования, качество или поставку."""

    id: str
    description: str
    category: Optional[str] = None
    probability: Optional[str] = None
    impact: Optional[str] = None
    severity: Optional[str] = None
    mitigation: Optional[str] = None
    contingency: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = None

    affects: Annotated[
        list["Requirement"],
        LinkMeta(kind="directed", role="affects", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)
    threatens: Annotated[
        list["QualityGoal"],
        LinkMeta(kind="directed", role="threatens", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)
    mitigated_by: Annotated[
        list["TechnicalStory"],
        LinkMeta(kind="directed", role="mitigatedBy", source_mult="0..*", target_mult="0..*"),
    ] = Field(default_factory=list)


class ConfidenceAssessment(BaseModel):
    """Оценка коэффициента уверенности для требования."""

    id: str
    value: float
    method: Optional[str] = None
    assessed_at: datetime = Field(default_factory=datetime.now)
    assessor: Optional[str] = None
    rationale: Optional[str] = None


class SourceArtifact(BaseModel):
    """Исходный Markdown-документ."""

    id: str
    file_path: str
    file_name: str
    document_version: Optional[str] = None
    commit_hash: Optional[str] = None
    language: Optional[str] = None
    total_chunks: Optional[int] = None
    parsing_status: ParsingStatus = Field(default=ParsingStatus.PENDING)

    chunks: Annotated[
        list["DocumentChunk"],
        LinkMeta(kind="composition", role="consistsOf", source_mult="1", target_mult="1..*"),
    ] = Field(default_factory=list)


class DocumentChunk(BaseModel):
    """Фрагмент Markdown-документа, подготовленный для LLM-анализа."""

    id: str
    chunk_index: int
    content: str
    token_count: Optional[int] = None
    start_offset: int = 0
    end_offset: int = 0
    markdown_path: Optional[str] = None
    overlap_size: Optional[int] = None
    content_hash: str
    metadata_json: Optional[str] = Field(default=None, alias="metadata")

    yields_req: Annotated[
        list["Requirement"],
        LinkMeta(kind="directed", role="yields", source_mult="1", target_mult="0..*"),
    ] = Field(default_factory=list)
    yields_terms: Annotated[
        list["TermUsage"],
        LinkMeta(kind="directed", role="yields", source_mult="1", target_mult="0..*"),
    ] = Field(default_factory=list)
    yields_constraints: Annotated[
        list["Constraint"],
        LinkMeta(kind="directed", role="yields", source_mult="1", target_mult="0..*"),
    ] = Field(default_factory=list)


class DomainGlossary(BaseModel):
    """Доменный глоссарий или его версия."""

    id: str
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    language: Optional[str] = None
    status: str = "draft"
    owner: Optional[str] = None

    terms: Annotated[
        list["GlossaryTerm"],
        LinkMeta(kind="composition", role="contains", source_mult="1", target_mult="0..*"),
    ] = Field(default_factory=list)


class GlossaryTerm(BaseModel):
    """Термин доменного глоссария."""

    id: str
    canonical_name: str
    definition: Optional[str] = None
    domain_area: Optional[str] = None
    language: Optional[str] = None
    status: GlossaryTermStatus = Field(default=GlossaryTermStatus.DRAFT)
    source: Optional[str] = None
    is_preferred: bool = False

    aliases: Annotated[
        list["TermAlias"],
        LinkMeta(kind="composition", role="hasAlias", source_mult="1", target_mult="0..*"),
    ] = Field(default_factory=list)


class TermAlias(BaseModel):
    """Синоним или альтернативное написание термина."""

    id: str
    alias: str
    language: Optional[str] = None
    usage_note: Optional[str] = None
    is_preferred: bool = False


class TermUsage(BaseModel):
    """Факт использования термина в тексте, кандидате или требовании."""

    id: str
    matched_text: str
    proposed_term: Optional[str] = None
    context_snippet: Optional[str] = None
    source_location: Optional[str] = None
    confidence: Optional[float] = None
    status: TermUsageStatus = Field(default=TermUsageStatus.DETECTED)
    extraction_method: Optional[str] = None
    detected_at: datetime = Field(default_factory=datetime.now)

    refers_to: Annotated[
        Optional["GlossaryTerm"],
        LinkMeta(kind="directed", role="refersTo", source_mult="0..*", target_mult="0..1"),
    ] = Field(default=None)
    used_in_requirement: Annotated[
        Optional["FunctionalRequirement"],
        LinkMeta(kind="directed", role="usedInRequirement", source_mult="0..*", target_mult="0..1"),
    ] = Field(default=None)
    found_in_candidate: Annotated[
        Optional["Requirement"],
        LinkMeta(kind="directed", role="foundInCandidate", source_mult="0..*", target_mult="0..1"),
    ] = Field(default=None)


class TermRelation(BaseModel):
    """Отношение между терминами глоссария."""

    id: str
    type: TermRelationType = Field(default=TermRelationType.RELATED)
    note: Optional[str] = None

    source_term: Annotated[
        "GlossaryTerm",
        LinkMeta(kind="directed", role="sourceTerm", source_mult="0..*", target_mult="1"),
    ] = Field(...)
    target_term: Annotated[
        "GlossaryTerm",
        LinkMeta(kind="directed", role="targetTerm", source_mult="0..*", target_mult="1"),
    ] = Field(...)


class BusinessConstraint(Constraint):
    """Бизнес-ограничение: регуляторное, бюджетное, сроковое."""

    regulation: Optional[str] = None
    standard: Optional[str] = None
    compliance_framework: Optional[str] = None
    budget_limit: Optional[float] = None
    deadline: Optional[date] = None


class TechnicalConstraint(Constraint):
    """Техническое ограничение: технология, протокол, платформа."""

    technology: Optional[str] = None
    protocol: Optional[str] = None
    architectural_pattern: Optional[str] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None


for _model in (
    Requirement,
    FunctionalRequirement,
    NonFunctionalRequirement,
    Link,
    Constraint,
    Criterion,
    Epic,
    Feature,
    UserStory,
    QualityGoal,
    TechnicalStory,
    Dependency,
    TraceabilityLink,
    AcceptanceCriterion,
    DoneCriterion,
    DefinitionOfDone,
    QualityAttribute,
    Risk,
    ConfidenceAssessment,
    SourceArtifact,
    DocumentChunk,
    DomainGlossary,
    GlossaryTerm,
    TermAlias,
    TermUsage,
    TermRelation,
    BusinessConstraint,
    TechnicalConstraint,
):
    _model.model_rebuild()

del _model