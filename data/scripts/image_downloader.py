"""제품 이미지를 내려받아 로컬에 저장한다.

원본은 `data/raw/images/` 에, 서비스에서 쓸 사본은 `data/processed/images/` 에 각각
저장한다. 지금은 가공 없이 원본을 그대로 복사하지만, 나중에 리사이즈·포맷 변환 같은
가공이 들어가면 `processed` 쪽만 바뀐다.
"""

from pathlib import Path
from urllib.parse import urlparse

import httpx

_RAW_IMAGE_DIR = Path("data/raw/images")
_PROCESSED_IMAGE_DIR = Path("data/processed/images")
_CONTENT_TYPE_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_DEFAULT_EXTENSION = ".jpg"

# 파일 앞부분 매직 바이트로 실제 포맷을 판별한다. 올리브영 글로벌 CDN 은 URL 확장자와
# Content-Type 헤더가 실제 바이트와 다른 경우가 있어(".png" 경로 + "image/png" 헤더인데
# 실제로는 JPEG인 상품을 확인함) 이게 유일하게 믿을 수 있는 판별 방법이다.
_MAGIC_BYTES_TO_EXTENSION: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"RIFF", ".webp"),  # WEBP 는 RIFF 컨테이너. 뒤 4바이트가 "WEBP" 인지까지는 구분 안 함.
)


class ImageDownloader:
    """이미지를 내려받아 raw/processed 두 곳에 저장하고, processed 쪽 로컬 경로를 반환한다."""

    _REQUEST_TIMEOUT_SECONDS = 30.0

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http_client = http_client or httpx.Client(
            timeout=self._REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        )

    def download(self, image_url: str, file_stem: str) -> Path:
        try:
            response = self._http_client.get(image_url)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimeError(f"이미지 다운로드 실패 (url={image_url!r}): {error}") from error

        extension = self._infer_extension(
            response.content, image_url, response.headers.get("content-type", "")
        )
        file_name = f"{file_stem}{extension}"

        raw_path = _RAW_IMAGE_DIR / file_name
        processed_path = _PROCESSED_IMAGE_DIR / file_name
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        processed_path.parent.mkdir(parents=True, exist_ok=True)

        raw_path.write_bytes(response.content)
        processed_path.write_bytes(response.content)

        return processed_path

    def _infer_extension(self, content: bytes, image_url: str, content_type: str) -> str:
        for magic_bytes, extension in _MAGIC_BYTES_TO_EXTENSION:
            if content.startswith(magic_bytes):
                return extension

        # 매직 바이트로 못 알아냈을 때만 헤더/URL 을 참고한다 (덜 믿을 수 있는 순서).
        extension_from_content_type = _CONTENT_TYPE_TO_EXTENSION.get(
            content_type.split(";")[0].strip()
        )
        if extension_from_content_type:
            return extension_from_content_type

        suffix = Path(urlparse(image_url).path).suffix
        return suffix if suffix else _DEFAULT_EXTENSION

    def close(self) -> None:
        self._http_client.close()
