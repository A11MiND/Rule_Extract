"""Verify JSON column works correctly with SQLite (no JSONB)."""
from sqlalchemy import Column, Integer, JSON, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class SQLiteDoc(Base):
    __tablename__ = "test_docs"
    id = Column(Integer, primary_key=True)
    manifest = Column(JSON, nullable=False, default=dict)
    sections = Column(JSON, nullable=False, default=list)


def test_json_column_serializes_and_deserializes(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    session = Session()
    session.add(SQLiteDoc(
        id=1,
        manifest={"key": "value", "nested": {"inner": 123}},
        sections=[{"id": "s1", "title": "Test"}],
    ))
    session.commit()

    result = session.query(SQLiteDoc).first()
    assert result.manifest == {"key": "value", "nested": {"inner": 123}}
    assert result.sections == [{"id": "s1", "title": "Test"}]
    assert result.manifest["nested"]["inner"] == 123