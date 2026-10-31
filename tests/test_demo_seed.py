from sqlalchemy import func, select

from database.models import Evaluation, Student, Teacher
from database.seed import SAMPLE_SHEET, seed_demo


def test_demo_seed_is_idempotent_and_contains_the_handwritten_sample(db_session):
    seed_demo(db_session)
    db_session.commit()
    teacher = db_session.scalar(select(Teacher).where(Teacher.is_demo_account.is_(True)))
    assert teacher is not None
    first_count = db_session.scalar(select(func.count()).select_from(Evaluation).where(Evaluation.is_demo.is_(True)))
    assert first_count == 12
    assert db_session.scalar(select(func.count()).select_from(Student).where(Student.is_demo.is_(True))) == 4
    assert SAMPLE_SHEET.exists()
    seed_demo(db_session)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Evaluation).where(Evaluation.teacher_id == teacher.id, Evaluation.is_demo.is_(True))) == 12
