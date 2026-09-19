from typing import Any

from data.scripts.nia_case_document_builder import TEXT_VERSION, NiaCaseDocumentBuilder
from data.scripts.nia_original_schemas import NiaOriginalRecord


def _raw_record(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "info": {
            "id": "COT_POR_F_O50_00143",
            "source_survey_id": "00143",
            "target_concern": "모공",
            "question": "  공백을 가진 질문\n두 번째 줄  ",
            "answer": "답변 본문",
            "evidence_sources": ["PMID:1", "DOI:10.1/x"],
        },
        "meta": {
            "gender": "여성",
            "age": 52,
            "initial_skin_condition": "NS/P1/W1/NA/VP/SA/ND/R",
            "skin_type": "복합성",
            "skin_concerns": ["모공", "미백(색소침착/기미/칙칙함)"],
            "image_filename": "03423.jpg",
        },
        "external": [
            {"priority": 1, "factor": "자외선/블루라이트", "details": "햇빛(UV)"},
            {"priority": 2, "factor": "스트레스", "details": "업무환경"},
        ],
        "chain_of_thought": [
            {"step": 1, "title": "문제 분석 및 원인 파악", "content": "내용1"},
            {"step": 2, "title": "성분 선택 및 근거 제시", "content": "내용2"},
            {"step": 3, "title": "사용법 및 관리방안", "content": "내용3"},
        ],
    }
    raw.update(overrides)
    return raw


def _build(raw: dict[str, Any]):
    return NiaCaseDocumentBuilder().build(NiaOriginalRecord.model_validate(raw))


def test_page_content가_질문_답변_추론_전체를_정해진_형식으로_담는다() -> None:
    document = _build(_raw_record())

    assert document.page_content == (
        "[질문]\n  공백을 가진 질문\n두 번째 줄  \n\n"
        "[답변]\n답변 본문\n\n"
        "[추론]\n1. 문제 분석 및 원인 파악\n내용1\n\n"
        "2. 성분 선택 및 근거 제시\n내용2\n\n"
        "3. 사용법 및 관리방안\n내용3"
    )


def test_CoT_순서는_원본_배열_순서를_따른다() -> None:
    raw = _raw_record()
    raw["chain_of_thought"] = [
        {"step": 2, "title": "B", "content": "b"},
        {"step": 1, "title": "A", "content": "a"},
    ]

    content = _build(raw).page_content

    assert content.index("2. B") < content.index("1. A")


def test_다단계_CoT도_문서_한_건에_들어간다() -> None:
    raw = _raw_record()
    raw["chain_of_thought"] = [
        {"step": n, "title": f"제목{n}", "content": f"내용{n}"} for n in range(1, 8)
    ]

    document = _build(raw)

    assert all(f"{n}. 제목{n}\n내용{n}" in document.page_content for n in range(1, 8))
    assert document.page_content.count("[질문]") == 1


def test_원문을_strip하거나_바꾸지_않는다() -> None:
    document = _build(_raw_record())

    assert "  공백을 가진 질문\n두 번째 줄  " in document.page_content


def test_metadata가_원본_값을_유실_없이_보존한다() -> None:
    metadata = _build(_raw_record()).metadata

    assert metadata.case_id == "COT_POR_F_O50_00143"
    assert metadata.source_survey_id == "00143"
    assert metadata.target_concern == "모공"
    assert metadata.gender == "여성"
    assert metadata.age == 52
    assert metadata.skin_type == "복합성"
    assert metadata.skin_concerns == ["모공", "미백(색소침착/기미/칙칙함)"]
    assert metadata.initial_skin_condition == "NS/P1/W1/NA/VP/SA/ND/R"
    assert metadata.image_filename == "03423.jpg"
    assert metadata.evidence_sources == ["PMID:1", "DOI:10.1/x"]
    assert [(e.priority, e.factor, e.details) for e in metadata.external] == [
        (1, "자외선/블루라이트", "햇빛(UV)"),
        (2, "스트레스", "업무환경"),
    ]


def test_initial_skin_condition과_external은_page_content에_들어가지_않는다() -> None:
    content = _build(_raw_record()).page_content

    assert "NS/P1/W1" not in content
    assert "자외선/블루라이트" not in content


def test_document_식별자와_embedding_text_v1_계약() -> None:
    document = _build(_raw_record())

    assert document.case_id == "COT_POR_F_O50_00143"
    assert document.embedding_text == document.page_content
    assert document.text_version == TEXT_VERSION


def test_비어_있는_리스트_필드가_있어도_문서를_만든다() -> None:
    raw = _raw_record(external=[], chain_of_thought=[])
    raw["info"]["evidence_sources"] = []
    raw["meta"]["skin_concerns"] = []

    document = _build(raw)

    assert document.page_content == "[질문]\n  공백을 가진 질문\n두 번째 줄  \n\n[답변]\n답변 본문"
    assert document.metadata.external == []
    assert document.metadata.evidence_sources == []
    assert document.metadata.skin_concerns == []
