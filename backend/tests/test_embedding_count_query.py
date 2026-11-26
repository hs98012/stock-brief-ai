from sqlalchemy import event
from app.embedding_service import embedding_counts
from tests.test_analysis import ready_document


def test_count_endpoint_does_not_materialize_embedding_vectors(db):
    document, _ = ready_document(db)
    statements = []
    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(db.get_bind(), 'before_cursor_execute', capture)
    try:
        assert embedding_counts(db, document.id, document.embedding_provider,
                                document.embedding_model, document.embedding_dimensions) == (1, 1, 0)
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', capture)
    assert not any('chunks.content AS' in statement or 'chunks.embedding AS' in statement for statement in statements)
