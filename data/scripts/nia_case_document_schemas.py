"""NIA 사례 검색용 Document(사례 1건 = 문서 1건)의 논리 구조.

벡터 저장소(Chroma, pgvector 등)에 넣는 형태가 아니라 저장소와 무관한 논리 구조다. list/객체
metadata 를 JSON 문자열이나 boolean 키로 펴는 일은 저장소 어댑터의 몫이라 여기서 하지 않는다.
그래야 저장소가 바뀌어도 이 계약이 바뀌지 않고, 원본 정보도 잃지 않는다.
"""

from pydantic import BaseModel, ConfigDict

from data.scripts.nia_original_schemas import NiaExternalFactor


class NiaCaseMetadata(BaseModel):
    """검색 filter 후보, 문맥, 출처를 원본 값 그대로 담는다. 정규화나 연령대 변환은 하지 않는다."""

    model_config = ConfigDict(frozen=True)

    # provenance
    case_id: str
    source_survey_id: str
    image_filename: str
    evidence_sources: list[str]

    # filter 후보
    target_concern: str
    gender: str
    age: int
    skin_type: str
    skin_concerns: list[str]

    # filter 정책이 아직 없는 문맥 정보. 잃지 않고 보존만 한다
    initial_skin_condition: str
    external: list[NiaExternalFactor]


class NiaCaseDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    page_content: str
    # v1 은 page_content 와 같다. 필드를 나눠 둔 이유는 저장 본문을 건드리지 않고 embedding
    # 입력만 바꾸는 실험(예: 질문+답변만)을 가능하게 하기 위해서다
    embedding_text: str
    text_version: str
    metadata: NiaCaseMetadata
