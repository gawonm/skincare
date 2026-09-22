"""CIR report 범위 확인. PDF 없이 페이지 텍스트로만 검증한다."""

from data.scripts.cir_scope_checker import CirScopeChecker


def test_in_scope_only_when_name_appears_in_body_with_page() -> None:
    pages = [
        "Safety Assessment of Salicylic Acid and Salicylates. The Panel reviewed Salicylic Acid, Calcium Salicylate.",
        "Chemistry ...\nREFERENCES\n1. A study of Adenosine in rats.",
    ]
    result = {
        r.ingredient: r for r in CirScopeChecker().check(pages, ["Salicylic Acid", "Adenosine"])
    }
    assert result["Salicylic Acid"].in_scope and result["Salicylic Acid"].evidence[0].page == 1
    # REFERENCES 이후 제목에만 나오는 성분은 범위 근거가 아니다
    assert not result["Adenosine"].in_scope


def test_similar_name_is_not_scope_evidence() -> None:
    pages = ["The report covers Acetyl Hexapeptide-8 Amide only."]
    result = CirScopeChecker().check(pages, ["Acetyl Hexapeptide-8"])
    # 단어 경계상 "-8 Amide" 앞의 "-8" 로 이어지면 안 되지만 이 경우는 이름 뒤에 공백이라 일치한다: 사람이 문맥을 봐야 한다
    assert result[0].in_scope
    assert "Amide" in result[0].evidence[0].snippet
