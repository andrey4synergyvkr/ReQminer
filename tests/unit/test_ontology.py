from contracts.ontology import (
    Dependency,
    DependencyType,
    DoneCriterion,
    Epic,
    Feature,
    LinkMeta,
    QualityAttribute,
    QualityGoal,
    UserStory,
)


def test_link_meta_metadata():
    field = Epic.model_fields["features"]
    meta = next(m for m in field.metadata if isinstance(m, LinkMeta))
    assert meta.kind == "aggregation"
    assert meta.role == "groups"
    assert meta.source_mult == "0..1"
    assert meta.target_mult == "0..*"


def test_epic_feature_userstory_hierarchy():
    user_story = UserStory(id="US-1", title="Оформить заказ")
    feature = Feature(id="F-1", title="Корзина", user_stories=[user_story])
    epic = Epic(id="E-1", title="Интернет-магазин", features=[feature])

    assert epic.features[0].user_stories[0].title == "Оформить заказ"


def test_dependency_link():
    source = UserStory(id="US-1", title="Оформить заказ")
    target = UserStory(id="US-2", title="Оплатить заказ")
    dep = Dependency(source=source, target=target, type=DependencyType.UNSPECIFIED)

    assert dep.source.id == "US-1"
    assert dep.target.id == "US-2"


def test_quality_goal_addresses():
    attr = QualityAttribute(id="QA-1", name="Время отклика")
    goal = QualityGoal(id="QG-1", title="Производительность", addresses=[attr])

    assert goal.addresses[0] is attr


def test_definition_of_done_contains_min_length():
    from pydantic import ValidationError

    import pytest

    from contracts.ontology import DefinitionOfDone

    DefinitionOfDone(id="DOD-1", name="Готовность истории", contains=[DoneCriterion(id="DC-1", description="Код слит в master")])
    with pytest.raises(ValidationError):
        DefinitionOfDone(contains=[])


def test_serialization():
    epic = Epic(id="E-1", title="Интернет-магазин")

    dumped = epic.model_dump()
    assert dumped["id"] == "E-1"
    assert dumped["title"] == "Интернет-магазин"
    assert "features" in dumped
