# DB 기반 Product Taxonomy 연동 상태

- 기록 일시: 2026-09-21 18:32 KST
- 대상 브랜치: `integration/nia-case-rag`
- 확인 범위: 2-Layer CLI, Trace CLI, Agent 조립, Backend 운영 진입점
- DB·마이그레이션 변경: 없음

## 1. 목표

고정된 `FixtureProductTaxonomy` 대신 DB `product` 테이블의 최신 분류값으로
`ProductTaxonomy`를 동적으로 구성한다.

사용하는 DB 컬럼은 다음과 같다.

- `product.service_category`: Agent의 상위 상품 분류 코드와 이름
- `product.product_type_normalized`: 해당 분류의 검색 별칭

이 구조를 사용하면 Agent가 질문에서 해석하는 상품 분류와 실제 상품 검색 결과의 분류가 같은
DB 값을 기준으로 동작한다.

## 2. 현재 구현 상태

| 범위 | 상태 | 설명 |
| --- | --- | --- |
| DB Taxonomy 집계 Repository | 완료 | NULL이 아닌 `service_category`, `product_type_normalized` 조합과 상품 수를 집계한다. |
| `ProductTaxonomy` 변환 Provider | 완료 | DB 집계를 카테고리와 별칭으로 변환하고 결정적 버전을 만든다. |
| 일반 2-Layer CLI | 완료 | CLI 시작 시 DB Taxonomy를 조회해 Agent에 명시적으로 주입한다. |
| 2-Layer Trace CLI | 완료 | 일반 CLI와 동일한 DB Taxonomy를 주입한다. |
| Agent 질문 해석·상품 필터 | 완료 | 주입된 DB Taxonomy를 Intent LLM 입력과 상품 필터 검증에 사용한다. |
| 실제 Backend API 운영 조립부 | 미완료·확인 필요 | Provider를 호출해 `ProductionAgentDependencies.product_taxonomy`에 넣는 애플리케이션 진입점은 현재 확인되지 않는다. |

## 3. 구현 위치

### DB 집계

`backend/repositories/agent_product_repository.py`

- `AgentProductReadRepository.list_taxonomy()`
- `product` 테이블에서 분류 조합을 읽는다.
- DB 쿼리는 Backend Repository에만 둔다.

### Agent 계약 변환

`backend/services/two_layer_rag_adapters.py`

- `TwoLayerProductTaxonomyProvider.load()`
- `service_category`를 `ProductCategory.code`, `ProductCategory.name`으로 변환한다.
- 같은 카테고리의 `product_type_normalized`를 `aliases`로 묶는다.
- `textures`, `skin_feels`는 빈 목록으로 유지한다. DB 세부 유형을 제형·사용감으로 추측하지 않기 위해서다.
- 정렬된 DB 분류와 상품 수로 `product-taxonomy/db-v1:<digest>` 버전을 만든다.

### CLI 주입

`tests/agent/interactive_two_layer_rag_cli.py`와
`tests/agent/interactive_two_layer_rag_trace_cli.py`

```text
ConfiguredDatabaseFactory
→ TwoLayerProductTaxonomyProvider.load()
→ DevelopmentAgentFactory(product_taxonomy=DB taxonomy)
→ AgentNodes
```

CLI가 `product_taxonomy`를 명시적으로 전달하므로 `DevelopmentAgentFactory`의 fixture fallback은
사용되지 않는다.

## 4. 실행 결과에서 확인하는 방법

DB Taxonomy가 연결된 CLI 배너는 다음 형태로 표시된다.

```text
상품 taxonomy: product-taxonomy/db-v1:297fb5629083
히스토리·체크포인터·루틴: 개발용 메모리 구현
```

두 번째 줄의 `개발용 메모리 구현`은 상품 Taxonomy를 뜻하지 않는다. 현재 메모리 구현인
히스토리·체크포인터 등을 뜻한다. 상품 Taxonomy는 첫 번째 줄의 DB 버전이 적용된 상태다.

다음처럼 나오면 DB Taxonomy 적용 여부를 다시 확인해야 한다.

```text
상품 taxonomy: fixture/...
```

## 5. `FixtureProductTaxonomy`가 아직 남아 있는 이유

`FixtureProductTaxonomy` 클래스 자체는 제거하지 않았다.

- DB 없이 실행하는 Agent 단위 테스트
- 개발용 `DevelopmentAgentFactory` 기본 fallback
- 고정된 카테고리 조건이 필요한 계약 테스트

에서 계속 사용한다. 코드에 fixture가 남아 있다는 사실만으로 실제 2-Layer CLI가 fixture를 쓰는
것은 아니다. 조립 시 `product_taxonomy`를 명시적으로 주입했는지를 기준으로 판단해야 한다.

## 6. 남은 작업

실제 Backend API에서도 같은 Taxonomy를 사용하려면 애플리케이션 시작 또는 Agent 의존성 조립
시점에 다음 연결이 필요하다.

```text
DB session factory
→ TwoLayerProductTaxonomyProvider.load()
→ ProductionAgentDependencies.product_taxonomy
→ ProductionAgentFactory.create()
```

이 연결 전에는 “CLI 기반 2-Layer Agent는 완료, Backend 운영 진입점은 미완료”로 판단한다.
Backend 조립부를 수정할 때는 Backend 담당 범위이므로 `docs/contracts/backend-to-agent.md`의
DB 기반 Product Taxonomy 조회 계약을 기준으로 연결해야 한다.

## 7. 결론

- 2-Layer 일반 CLI: DB Taxonomy 적용 완료
- 2-Layer Trace CLI: DB Taxonomy 적용 완료
- CLI가 실행하는 실제 Agent 필터: DB Taxonomy 적용 완료
- 단위 테스트·개발 fallback: fixture 유지
- Backend API 운영 Agent 조립: 추가 연결 필요

