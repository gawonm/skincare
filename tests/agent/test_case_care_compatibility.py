"""현재 피부 상태에 맞지 않는 Case 조언을 골라내는 회귀 검사."""

from agent.rag.retrieval.case_care_compatibility import CaseCareCompatibilityPolicy
from agent.rag.schemas import CareContext, CarePriority, IrritationStatus


class TestCaseCareCompatibilityPolicy:
    def test_복합_질의에서_놓친_각질_제거_권고를_제외한다(self) -> None:
        policy = CaseCareCompatibilityPolicy()
        context = self._recovery_context()
        answers = [
            "부드러운 각질 제거를 시행하여 모공을 관리합니다.",
            "주 1~2회 부드러운 각질 제거를 통해 피부결을 개선합니다.",
            "이중 클렌징을 실시하고, 주 1-2회 각질 제거를 통해 모공을 관리합니다.",
            "리치 씨앗 가루로 각질을 부드럽게 제거하고 피부를 진정시킵니다.",
            "정기적인 저자극 각질 관리와 보습이 중요한 관리 방안입니다.",
        ]

        assert all(
            policy.assess(context, f"[답변]\n{answer}").is_incompatible()
            for answer in answers
        )

    def test_금지와_회복_후_조건을_현재_권고로_판정하지_않는다(self) -> None:
        policy = CaseCareCompatibilityPolicy()
        context = self._recovery_context()
        answers = [
            "각질 제거는 피하고 보습 관리를 실시하세요.",
            "피부가 회복된 후 각질 제거를 주 1회 실시하세요.",
            "BHA는 중단하고, 보습제를 사용하세요.",
            "미네랄 솔트는 각질 관리에 도움을 주며 보습제를 사용하세요.",
        ]

        assert all(
            not policy.assess(context, f"[답변]\n{answer}").is_incompatible()
            for answer in answers
        )

    def test_금지된_절과_권고된_절이_함께_있으면_권고를_잡는다(self) -> None:
        assessment = CaseCareCompatibilityPolicy().assess(
            self._recovery_context(),
            "[답변]\n스크럽은 피하고, BHA 토너를 사용하세요.",
        )

        assert assessment.is_incompatible()

    def test_위험_성분과_권고_동사가_다른_절에_있어도_제외한다(self) -> None:
        assessment = CaseCareCompatibilityPolicy().assess(
            self._recovery_context(),
            "[답변]\nBHA, 나이아신아이드와 레티놀 성분을 활용하세요.",
        )

        assert assessment.is_incompatible()

    def test_회복_우선_상태가_아니면_같은_권고도_제외하지_않는다(self) -> None:
        assessment = CaseCareCompatibilityPolicy().assess(
            CareContext(
                irritation_status=IrritationStatus.INACTIVE,
                priority=CarePriority.STANDARD,
            ),
            "[답변]\n주 1~2회 각질 제거를 실시하세요.",
        )

        assert not assessment.is_incompatible()

    def _recovery_context(self) -> CareContext:
        return CareContext(
            irritation_status=IrritationStatus.ACTIVE,
            priority=CarePriority.RECOVERY,
        )
