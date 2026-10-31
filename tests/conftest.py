from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.models import Base, Examination, Question, Student, Teacher
from schemas import MarkingQuestion, MarkingScheme


_test_temp = Path(__file__).resolve().parents[1] / ".test-tmp"
_test_temp.mkdir(exist_ok=True)
os.environ["TEMP"] = str(_test_temp)
os.environ["TMP"] = str(_test_temp)
tempfile.tempdir = str(_test_temp)


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def _fk(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    teacher = Teacher(name="Test Teacher", institution="Test School", email="test@example.com")
    student = Student(teacher=teacher, name="Avery Student", student_code="T-1", class_grade="Grade 8")
    exam = Examination(teacher=teacher, title="Unit Check", subject="Maths", class_grade="Grade 8", academic_year="2026", total_marks=10, questions=[
        Question(number=1, prompt="Solve 2 + 2", expected_answer="4", max_marks=5, key_concepts=["addition"]),
        Question(number=2, prompt="Solve 3 + 4", expected_answer="7", max_marks=5, key_concepts=["addition"]),
    ])
    session.add_all([teacher, student, exam])
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def scheme():
    return MarkingScheme(questions=[
        MarkingQuestion(number=1, prompt="Solve 2 + 2", expected_answer="4", max_marks=5, key_concepts=["addition"]),
        MarkingQuestion(number=2, prompt="Solve 3 + 4", expected_answer="7", max_marks=5, key_concepts=["addition"]),
    ])
