from pgvector.sqlalchemy import Vector

from models.nia_case_document import NIA_CASE_EMBEDDING_DIMENSION, NiaCaseDocument


class TestNiaCaseDocumentModel:
    def test_embedding은_bge_m3_1024차원이다(self) -> None:
        column_type = NiaCaseDocument.__table__.c.embedding.type

        assert isinstance(column_type, Vector)
        assert column_type.dim == NIA_CASE_EMBEDDING_DIMENSION == 1024

    def test_자연키와_검색_index가_선언되어_있다(self) -> None:
        table = NiaCaseDocument.__table__
        constraint_names = {constraint.name for constraint in table.constraints}
        index_names = {index.name for index in table.indexes}

        assert "uq_nia_case_document_case_text_model" in constraint_names
        assert "ix_nia_case_document_embedding_hnsw" in index_names
        assert "ix_nia_case_document_retrieval_scope" in index_names
        assert "ix_nia_case_document_case_id" in index_names
