"""비밀번호 해싱. DB도 HTTP도 모르는 순수 로직만 둔다.

FastAPI 실무에서는 해싱/토큰 같은 순수 보안 로직을 전용 모듈에 모으고, 저장은 별도
계층(여기서는 `repositories/session.py`의 Redis 세션 저장소)에 맡긴다. 이 모듈은
`core/`에 두지 않는다. `core/`는 `agent/`와 공유되는데 `agent/`는 인증을 몰라야 하기
때문이다.

알고리즘은 argon2id(argon2-cffi 기본 파라미터). 파라미터 튜닝이 필요해지면 여기 한
곳만 바꾸면 되고, `needs_rehash`가 기존 해시를 다음 로그인 때 새 파라미터로 교체한다.
"""

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError


class PasswordHasher:
    """argon2id 해시 계산과 검증."""

    def __init__(self) -> None:
        self._hasher = Argon2PasswordHasher()

    def hash(self, password: str) -> str:
        """평문 비밀번호를 argon2id 해시 문자열로 만든다. 이 값만 DB에 저장한다."""
        return self._hasher.hash(password)

    def verify(self, hashed_password: str, password: str) -> bool:
        """평문이 저장된 해시와 일치하는지. 불일치는 정상 결과이므로 예외가 아니라 False로 돌려준다.

        저장된 해시 자체가 손상돼 파싱조차 되지 않는 경우는 데이터 문제이므로 숨기지 않고
        올린다. 어느 값이 문제인지 알 수 있게 원인을 붙인다.
        """
        try:
            self._hasher.verify(hashed_password, password)
        except VerifyMismatchError:
            return False
        except InvalidHashError as e:
            raise RuntimeError(f"저장된 비밀번호 해시를 해석할 수 없습니다: {e}") from e
        return True

    def needs_rehash(self, hashed_password: str) -> bool:
        """저장된 해시가 현재 파라미터보다 약한지. True면 로그인 성공 시 새 해시로 교체한다."""
        return self._hasher.check_needs_rehash(hashed_password)
